"""Load orchestrator runtime config."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List


@dataclass(frozen=True)
class MatrixHostConfig:
    id: str
    label: str
    api_base: str


@dataclass(frozen=True)
class MqttConfig:
    broker: str
    port: int
    test_topic: str


@dataclass(frozen=True)
class OffloadHostConfig:
    """A remote Whisper inference host (e.g. Radxa Q6A) fed by the Pi5 forwarder."""

    id: str
    label: str
    host: str
    ssh_user: str
    ssh_key: str
    ssh_port: int
    transcribe_service: str
    forwarder_service: str
    remote_config_path: str
    transcripts_dir: str
    chunks_dir: str


@dataclass(frozen=True)
class OrchestratorConfig:
    host: str
    port: int
    request_timeout_seconds: float
    matrix_hosts: List[MatrixHostConfig]
    mqtt: MqttConfig
    offload_hosts: List[OffloadHostConfig]
    messages: "MessagesConfig"


@dataclass(frozen=True)
class MessagesConfig:
    """Custom messages: retained MQTT copy for small displays that schedule locally."""

    topic: str = "spectra/messages/config"
    preview_topic: str = "spectra/messages/preview"
    timezone: str = "America/New_York"


DEFAULTS: dict[str, Any] = {
    "host": "0.0.0.0",
    "port": 8090,
    "request_timeout_seconds": 5.0,
    "matrix_hosts": [],
    "mqtt": {
        "broker": "127.0.0.1",
        "port": 1883,
        "test_topic": "whisper/transcript",
    },
    "offload_hosts": [],
}


def _config_paths() -> List[Path]:
    paths: List[Path] = []
    env_path = os.environ.get("SPECTRA_ORCHESTRATOR_CONFIG", "").strip()
    if env_path:
        paths.append(Path(env_path))
    data_root = os.environ.get("SPECTRA_DATA_ROOT", "/data/spectra")
    paths.extend(
        [
            Path(data_root) / "config" / "orchestrator.local.json",
            Path(__file__).resolve().parents[1] / "config" / "orchestrator.local.json",
            Path(__file__).resolve().parents[1] / "config" / "orchestrator.example.json",
        ]
    )
    return paths


def load_config() -> OrchestratorConfig:
    raw: dict[str, Any] = dict(DEFAULTS)
    for path in _config_paths():
        if path.is_file():
            with path.open(encoding="utf-8") as fh:
                raw.update(json.load(fh))
            break

    hosts = [
        MatrixHostConfig(
            id=str(item["id"]),
            label=str(item.get("label", item["id"])),
            api_base=str(item["api_base"]).rstrip("/"),
        )
        for item in raw.get("matrix_hosts", [])
    ]
    if not hosts:
        raise RuntimeError(
            "orchestrator config has no matrix_hosts — deploy orchestrator.local.json"
        )

    mqtt_raw = raw.get("mqtt") or {}
    mqtt = MqttConfig(
        broker=str(mqtt_raw.get("broker", "127.0.0.1")),
        port=int(mqtt_raw.get("port", 1883)),
        test_topic=str(mqtt_raw.get("test_topic", "whisper/transcript")),
    )

    offload_hosts = [
        OffloadHostConfig(
            id=str(item["id"]),
            label=str(item.get("label", item["id"])),
            host=str(item["host"]),
            ssh_user=str(item.get("ssh_user", "spectra")),
            ssh_key=str(
                item.get("ssh_key", "/data/spectra/config/controller_id_rsa.spectra")
            ),
            ssh_port=int(item.get("ssh_port", 22)),
            transcribe_service=str(
                item.get("transcribe_service", "spectra-whisper-transcribe")
            ),
            forwarder_service=str(
                item.get("forwarder_service", "spectra-whisper-forward")
            ),
            remote_config_path=str(
                item.get("remote_config_path", "/data/spectra/config/whisper.local.json")
            ),
            transcripts_dir=str(
                item.get("transcripts_dir", "/data/spectra/audio-capture/transcripts")
            ),
            chunks_dir=str(
                item.get("chunks_dir", "/data/spectra/audio-capture/chunks")
            ),
        )
        for item in raw.get("offload_hosts", [])
    ]

    return OrchestratorConfig(
        host=str(raw.get("host", "0.0.0.0")),
        port=int(raw.get("port", 8090)),
        request_timeout_seconds=float(raw.get("request_timeout_seconds", 5.0)),
        matrix_hosts=hosts,
        mqtt=mqtt,
        offload_hosts=offload_hosts,
        messages=MessagesConfig(**{
            k: str(v) for k, v in (raw.get("messages") or {}).items()
            if k in ("topic", "preview_topic", "timezone")
        }),
    )
