#!/usr/bin/env python3
"""Watch ReSpeaker chunk files, transcribe, publish MQTT.

ASR engine is chosen by ``engine`` in the config: ``cpu`` (faster-whisper) or
``npu`` (Whisper on the Hexagon DSP via asr_npu). Translation is a separate
stage -- see translate.py.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence

import paho.mqtt.client as mqtt

from filter import publish_filter_cfg, should_publish
from translate import (
    apply_post_translation_ex,
    build_mqtt_payload,
    build_transcript_meta,
    effective_translate_engine,
    flush_pending_translation,
    normalize_lang,
    resolve_translate_engine,
    transcribe_options,
)


def _config_paths() -> List[Path]:
    paths: List[Path] = []
    env_path = os.environ.get("SPECTRA_WHISPER_CONFIG", "").strip()
    if env_path:
        paths.append(Path(env_path))
    paths.extend(
        [
            Path("/data/spectra/config/whisper.local.json"),
            Path(__file__).resolve().parent / "config.local.json",
        ]
    )
    return paths


def load_config() -> Dict[str, Any]:
    for path in _config_paths():
        if path.is_file():
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
    raise SystemExit(
        "Whisper config not found. Deploy whisper.local.json or set SPECTRA_WHISPER_CONFIG."
    )


def file_is_stable(path: Path) -> bool:
    size1 = path.stat().st_size
    time.sleep(1)
    size2 = path.stat().st_size
    return size1 == size2 and size1 > 0


def build_model(cfg: Dict[str, Any]) -> Any:
    engine = str(cfg.get("engine", "cpu")).lower()

    if engine == "npu":
        from asr_npu import NpuWhisperModel

        print("Loading Whisper on the Hexagon NPU...", flush=True)
        return NpuWhisperModel(cfg)

    if engine != "cpu":
        raise SystemExit(f"Engine {engine!r} is not implemented yet; use cpu or npu.")

    from faster_whisper import WhisperModel

    model_name = str(cfg.get("model", "base"))
    compute_type = str(cfg.get("compute_type", "int8"))
    print(f"Loading faster-whisper model {model_name!r} ({compute_type})...", flush=True)
    return WhisperModel(model_name, device="cpu", compute_type=compute_type)


def transcribe(
    model: Any,
    media: Path,
    cfg: Dict[str, Any],
) -> tuple[str, str, list, Dict[str, Any]]:
    options, effective_engine = transcribe_options(cfg)
    target_language = normalize_lang(cfg.get("target_language", "en"), default="en")
    configured_engine = resolve_translate_engine(cfg)

    segments, info = model.transcribe(str(media), **options)
    seg_list = list(segments)
    source_text = " ".join(segment.text.strip() for segment in seg_list).strip()
    detected_language = getattr(info, "language", None)

    from translate import resolve_source_language

    source_language = resolve_source_language(cfg, detected_language)
    display_text = source_text
    original_text: str | None = None
    buffered = False

    if effective_engine == "off":
        translate_engine = "off"
    elif effective_engine == "whisper":
        translate_engine = "whisper"
        display_text = source_text
    else:
        translate_engine = effective_engine
        translated, consumed = apply_post_translation_ex(
            source_text,
            cfg,
            source_language=source_language,
            model=model,
        )
        if source_text and not consumed:
            # Held back to finish a sentence; it is emitted with a later chunk.
            buffered = True
            display_text = ""
        else:
            if translated.strip() != consumed.strip():
                original_text = consumed.strip()
            display_text = translated.strip()
            # A silent chunk can release text held from earlier ones; the
            # publish filter must judge that text, not this chunk's empty one.
            if consumed.strip():
                source_text = consumed.strip()

    if configured_engine == "whisper" and effective_engine == "argos":
        print(
            f"Note: whisper translate is English-only; using argos for "
            f"{source_language}→{target_language}",
            flush=True,
        )

    meta = build_transcript_meta(
        translate_engine=translate_engine,
        task=str(options["task"]),
        language=detected_language,
        language_probability=getattr(info, "language_probability", None),
        target_language=target_language,
        source_language=source_language,
        original_text=original_text,
    )
    if buffered:
        meta["buffered"] = True

    return display_text, source_text, seg_list, meta


def write_audit_files(
    transcripts_dir: Path,
    base: str,
    display_text: str,
    meta: Dict[str, Any],
) -> None:
    (transcripts_dir / f"{base}.txt").write_text(display_text + "\n", encoding="utf-8")
    (transcripts_dir / f"{base}.meta.json").write_text(
        json.dumps({"text": display_text, **meta}, indent=2) + "\n",
        encoding="utf-8",
    )
    (transcripts_dir / f"{base}.done").touch()


def _task_label(cfg: Dict[str, Any]) -> str:
    engine = effective_translate_engine(cfg)
    if engine == "off":
        return "transcribe"
    source = normalize_lang(
        cfg.get("source_language") or cfg.get("language", "auto"), default="auto"
    )
    target = normalize_lang(cfg.get("target_language", "en"), default="en")
    if engine == "whisper":
        return f"translate→{target}"
    return f"transcribe+{engine} ({source}→{target})"


def main() -> None:
    cfg = load_config()
    chunks_dir = Path(cfg["chunks_dir"])
    transcripts_dir = Path(cfg["transcripts_dir"])
    transcripts_dir.mkdir(parents=True, exist_ok=True)

    if not chunks_dir.is_dir():
        raise SystemExit(f"Chunks directory missing: {chunks_dir}")

    effective_engine = effective_translate_engine(cfg)
    if effective_engine == "ct2":
        from mt_ct2 import pin_to_big_cores

        if pin_to_big_cores():
            print("Pinned to the Cortex-A78 cores for CTranslate2", flush=True)

    model = build_model(cfg)
    task_label = _task_label(cfg)

    topic = str(cfg.get("topic", "whisper/transcript"))
    ttl = int(cfg.get("mqtt_ttl", 30))
    color = cfg.get("text_color", [255, 255, 255])
    poll_seconds = float(cfg.get("poll_seconds", 2))

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(str(cfg.get("broker", "127.0.0.1")), int(cfg.get("port", 1883)), 60)
    client.loop_start()

    print(
        f"Watching {chunks_dir} -> MQTT {topic} ({task_label}, engine={effective_engine})",
        flush=True,
    )

    filter_cfg = publish_filter_cfg(cfg)
    target_language = normalize_lang(cfg.get("target_language", "en"), default="en")

    def publish_result(
        display_text: str,
        source_text: str,
        segments: Sequence[Any],
        meta: Dict[str, Any],
        elapsed: float,
        label: str,
    ) -> None:
        publish, reason = should_publish(source_text, segments, filter_cfg)
        if publish:
            payload = build_mqtt_payload(display_text, meta, ttl=ttl, color=color)
            client.publish(topic, json.dumps(payload), qos=0)
            preview = display_text if len(display_text) <= 120 else display_text[:117] + "..."
            lang = meta.get("language")
            lang_note = f" [{lang}]" if lang else ""
            if meta.get("original_text"):
                lang_note += " translated"
            print(f"{label}{lang_note} ({elapsed:.1f}s): {preview}", flush=True)
        elif source_text or display_text:
            skipped = source_text or display_text
            print(f"Skipped publish ({reason}, {elapsed:.1f}s): {skipped[:80]}", flush=True)

    while True:
        media_files = sorted(chunks_dir.glob("*.wav")) + sorted(chunks_dir.glob("*.mp3"))
        for media in media_files:
            base = media.stem
            done_file = transcripts_dir / f"{base}.done"
            if done_file.exists():
                continue
            if not file_is_stable(media):
                print(f"Skipping growing file: {media.name}", flush=True)
                continue

            print(f"Transcribing {media.name}...", flush=True)
            started = time.monotonic()
            display_text, source_text, segments, meta = transcribe(model, media, cfg)
            elapsed = time.monotonic() - started
            write_audit_files(transcripts_dir, base, display_text, meta)

            if meta.get("buffered"):
                print(
                    f"Buffered ({elapsed:.1f}s, awaiting sentence end): "
                    f"{source_text[:70]}",
                    flush=True,
                )
            elif not source_text and not display_text:
                print(f"No speech detected in {media.name}", flush=True)
            else:
                publish_result(
                    display_text, source_text, segments, meta, elapsed, "Published"
                )

        # Release fragments the translator is holding when no more audio arrives,
        # otherwise trailing speech waits for a chunk that may never come.
        for source_language, flushed, consumed in flush_pending_translation(cfg):
            flush_meta = build_transcript_meta(
                translate_engine=effective_engine,
                task="transcribe",
                language=source_language,
                language_probability=None,
                target_language=target_language,
                source_language=source_language,
                original_text=consumed,
            )
            publish_result(flushed, consumed, (), flush_meta, 0.0, "Flushed")

        time.sleep(poll_seconds)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
