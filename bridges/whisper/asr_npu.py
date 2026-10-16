"""Hexagon NPU ASR engine for the Whisper bridge.

Wraps the ``whisper-npu-host`` helper, which runs Whisper on the QCS6490
Hexagon DSP via Qualcomm's VoiceAI SDK. The helper is held open in
``--serve-files`` mode and fed one wav path per line, because:

* initialising the model costs ~1s, so a process per chunk is wasteful; and
* the DSP has only 12 FastRPC compute contexts and leaks one per process that
  does not shut down cleanly, so short-lived processes eventually wedge the DSP.

``NpuWhisperModel.transcribe`` deliberately mirrors the small part of the
faster-whisper API that ``transcribe_watch.py`` uses, so the surrounding code is
unchanged. The confidence fields faster-whisper supplies are not available from
the SDK -- see ``NpuSegment``.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Layout installed by the whisper_npu Ansible role.
DEFAULT_BINARY = "/data/spectra/opt/whisper-npu-host/bin/whisper-npu-host"
DEFAULT_MODEL_DIR = "/data/spectra/vendor/whisper_models/ai_hub_small_quantized"
DEFAULT_ENV_SCRIPT = "/data/spectra/opt/whisper-npu-host/env.sh"

# The SDK is chatty on stdout; bound how much noise we skip looking for a message.
_MAX_NOISE_LINES = 200


class NpuUnavailable(RuntimeError):
    """The NPU helper could not be started or died unrecoverably."""


@dataclass
class NpuSegment:
    """Stand-in for a faster-whisper segment.

    The VoiceAI SDK reports no per-segment confidence, so ``no_speech_prob`` and
    ``avg_logprob`` are neutral values that pass filter.py's thresholds. Silence
    rejection is instead done by the SDK's own VAD before the text ever appears,
    and filter.py's length and reject-phrase rules still apply.
    """

    text: str
    no_speech_prob: float = 0.0
    avg_logprob: float = 0.0


@dataclass
class NpuInfo:
    language: Optional[str]
    language_probability: Optional[float] = None


# The SDK reports language names ("Russian"); the rest of the pipeline uses codes.
_NAME_TO_CODE = {
    "english": "en", "russian": "ru", "ukrainian": "uk", "chinese": "zh",
    "german": "de", "french": "fr", "spanish": "es", "polish": "pl",
    "belarusian": "be", "kazakh": "kk", "arabic": "ar", "turkish": "tr",
    "japanese": "ja", "korean": "ko", "italian": "it", "portuguese": "pt",
    "persian": "fa", "hebrew": "he", "dutch": "nl", "czech": "cs",
    "romanian": "ro", "hungarian": "hu", "greek": "el", "bulgarian": "bg",
    "serbian": "sr", "croatian": "hr", "georgian": "ka", "armenian": "hy",
    "azerbaijani": "az", "uzbek": "uz",
}


def language_to_code(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) <= 3 and text.islower():
        return text
    return _NAME_TO_CODE.get(text.lower(), text.lower()[:2])


def _load_env_script(path: str) -> Dict[str, str]:
    """Read the simple ``export K=V`` pairs the helper needs (LD_LIBRARY_PATH etc)."""
    env = dict(os.environ)
    p = Path(path)
    if not p.is_file():
        return env
    # Let the shell expand the script's own variable references, then read it back.
    out = subprocess.run(
        ["bash", "-c", f"set -a; . {shlex.quote(str(p))}; env -0"],
        capture_output=True, text=False, check=False,
    )
    if out.returncode != 0:
        return env
    for item in out.stdout.split(b"\0"):
        if not item or b"=" not in item:
            continue
        k, v = item.split(b"=", 1)
        env[k.decode()] = v.decode(errors="replace")
    return env


class NpuWhisperModel:
    def __init__(self, cfg: Dict[str, Any]) -> None:
        npu = cfg.get("npu", {}) if isinstance(cfg.get("npu"), dict) else {}
        self._binary = str(npu.get("binary", DEFAULT_BINARY))
        self._model_dir = str(npu.get("model_dir", DEFAULT_MODEL_DIR))
        self._env_script = str(npu.get("env_script", DEFAULT_ENV_SCRIPT))
        self._timeout_ms = int(npu.get("timeout_ms", 60000))
        self._log_path = str(npu.get("log_path", "")).strip()
        self._read_timeout = float(npu.get("read_timeout_seconds", 120))
        # The language the helper is started with; changing it needs a restart.
        lang = cfg.get("language")
        self._lang = "auto" if lang in (None, "", "auto") else str(lang)
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._env = _load_env_script(self._env_script)
        if not Path(self._binary).is_file():
            raise NpuUnavailable(f"NPU helper not found: {self._binary}")
        if not Path(self._model_dir).is_dir():
            raise NpuUnavailable(f"NPU model dir not found: {self._model_dir}")
        self._start()

    # -- process management -------------------------------------------------
    def _start(self) -> None:
        cmd = [self._binary, "--model", self._model_dir,
               "--lang", self._lang, "--serve-files",
               "--timeout", str(self._timeout_ms)]
        if self._log_path:
            stderr: Any = open(self._log_path, "ab", buffering=0)
        else:
            stderr = subprocess.DEVNULL
        self._proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=stderr, env=self._env, text=True, bufsize=1,
        )
        ready = self._readline()
        if ready is None or ready.get("type") != "ready":
            self._kill()
            raise NpuUnavailable(f"NPU helper did not report ready (got {ready!r})")
        print(f"NPU ASR ready (init {ready.get('init_ms')} ms, lang={self._lang})", flush=True)

    def _kill(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()          # clean shutdown releases the DSP session
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except Exception:
                pass

    def close(self) -> None:
        with self._lock:
            self._kill()

    def _readline(self) -> Optional[Dict[str, Any]]:
        """Next JSON message from the helper, or None at EOF.

        The Qualcomm SDK libraries print diagnostics to stdout, mixed in with our
        protocol, so anything that is not a JSON object is skipped.
        """
        proc = self._proc
        if proc is None or proc.stdout is None:
            return None
        for _ in range(_MAX_NOISE_LINES):
            line = proc.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict):
                return msg
        return None

    # -- faster-whisper-shaped API -----------------------------------------
    def transcribe(self, media: str, **options: Any) -> Tuple[Iterable[NpuSegment], NpuInfo]:
        task = str(options.get("task", "transcribe"))
        if task == "translate":
            raise NpuUnavailable(
                "The NPU model does not support Whisper's translate task "
                "(it returns empty output). Set translate_engine to 'ct2' or 'argos'."
            )

        with self._lock:
            result = self._request(media)
            if result is None:
                # One restart attempt: a wedged DSP or a crashed helper is recoverable.
                print("NPU helper stopped responding; restarting", flush=True)
                self._kill()
                self._start()
                result = self._request(media)
            if result is None:
                raise NpuUnavailable("NPU helper failed twice; giving up on this chunk")

        text = str(result.get("text", "")).strip()
        code = language_to_code(result.get("language"))
        segments: List[NpuSegment] = [NpuSegment(text=text)] if text else []
        return segments, NpuInfo(language=code)

    def _request(self, media: str) -> Optional[Dict[str, Any]]:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            return None
        try:
            proc.stdin.write(f"{media}\n")
            proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            return None
        while True:
            msg = self._readline()
            if msg is None:
                return None
            if msg.get("type") == "result":
                return msg
            # ignore any other message types (events, errors) and keep waiting
