"""Start/stop Pi5 Whisper capture + transcribe systemd units from the orchestrator."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

CAPTURE_SERVICE = "spectra-whisper-capture"
# Second Pi5 service depends on deployment: offload hosts run the forwarder here
# (transcribe lives on the offload host); local deployments run transcribe here.
FORWARD_SERVICE = "spectra-whisper-forward"
TRANSCRIBE_SERVICE = "spectra-whisper-transcribe"


@dataclass(frozen=True)
class WhisperStatus:
    enabled: bool
    services: Dict[str, str]
    translate_engine: str = "off"
    language: str = "auto"
    target_language: str = "en"

    def as_dict(self) -> dict:
        out = {
            "enabled": self.enabled,
            "services": dict(self.services),
        }
        if self.translate_engine != "off":
            out["translate_engine"] = self.translate_engine
            out["language"] = self.language
            out["target_language"] = self.target_language
        return out


def _read_whisper_config() -> Dict[str, str]:
    path = Path("/data/spectra/config/whisper.local.json")
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "translate_engine": str(data.get("translate_engine", "off")),
        "language": str(data.get("language", "auto")),
        "target_language": str(data.get("target_language", "en")),
    }


def _run(cmd: List[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _service_state(unit: str) -> str:
    result = _run(["systemctl", "is-active", unit])
    state = (result.stdout or result.stderr or "unknown").strip()
    return state or "unknown"


def _second_service() -> str:
    """Pick the Pi5's second pipeline unit: forwarder (offload) or transcribe (local)."""
    result = _run(["systemctl", "is-enabled", FORWARD_SERVICE])
    if (result.stdout or "").strip() in ("enabled", "enabled-runtime", "static"):
        return FORWARD_SERVICE
    return TRANSCRIBE_SERVICE


def _pi5_services() -> List[str]:
    return [CAPTURE_SERVICE, _second_service()]


def get_status() -> WhisperStatus:
    services = {unit: _service_state(unit) for unit in _pi5_services()}
    enabled = all(state == "active" for state in services.values())
    cfg = _read_whisper_config()
    return WhisperStatus(
        enabled=enabled,
        services=services,
        translate_engine=str(cfg.get("translate_engine", "off")),
        language=str(cfg.get("language", "auto")),
        target_language=str(cfg.get("target_language", "en")),
    )


def set_enabled(enabled: bool) -> WhisperStatus:
    verb = "start" if enabled else "stop"
    units = [f"{unit}.service" for unit in _pi5_services()]
    result = _run(["sudo", "-n", "systemctl", verb, *units])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or f"systemctl {verb} failed"
        raise RuntimeError(detail)
    return get_status()


def _local_audio_dirs() -> tuple[Path, Path]:
    path = Path("/data/spectra/config/whisper.local.json")
    chunks = Path("/data/spectra/audio-capture/chunks")
    transcripts = Path("/data/spectra/audio-capture/transcripts")
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                chunks = Path(str(data.get("chunks_dir", chunks)))
                transcripts = Path(str(data.get("transcripts_dir", transcripts)))
        except (OSError, json.JSONDecodeError):
            pass
    return chunks, transcripts


def count_pending_queue() -> int:
    """Chunks on disk without a matching transcripts .done marker."""
    chunks_dir, transcripts_dir = _local_audio_dirs()
    if not chunks_dir.is_dir():
        return 0
    pending = 0
    for pattern in ("*.wav", "*.mp3"):
        for media in chunks_dir.glob(pattern):
            if not (transcripts_dir / f"{media.stem}.done").is_file():
                pending += 1
    return pending


def purge_pending_queue() -> int:
    """Delete Pi5-local chunks not yet transcribed. Returns files removed."""
    chunks_dir, transcripts_dir = _local_audio_dirs()
    if not chunks_dir.is_dir():
        return 0
    deleted = 0
    for pattern in ("*.wav", "*.mp3"):
        for media in sorted(chunks_dir.glob(pattern)):
            if (transcripts_dir / f"{media.stem}.done").is_file():
                continue
            try:
                media.unlink()
                deleted += 1
            except OSError as exc:
                raise RuntimeError(f"Failed to delete {media.name}: {exc}") from exc
    return deleted
