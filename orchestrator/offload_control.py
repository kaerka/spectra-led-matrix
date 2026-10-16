"""Probe remote Whisper inference (offload) hosts from the Pi5 orchestrator.

The Pi5 forwards audio chunks to an offload host (e.g. Radxa Q6A) which runs
`spectra-whisper-transcribe` and publishes captions back to MQTT. This module
reports:

- the Pi5-local forwarder service state (local `systemctl`),
- the offload host's transcribe service state + active model + freshest caption
  age (one short SSH call using the controller deploy key).
"""

from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import List, Optional

from orchestrator.config import OffloadHostConfig

# Remote probe: transcribe state, model, caption age, pending chunk count (python — fast on large dirs).
_REMOTE_SCRIPT = (
    "STATE=$(systemctl is-active {service} 2>/dev/null); "
    # "model" is the faster-whisper size and is ignored when engine is npu.
    "MODEL=$(python3 -c 'import json;c=json.load(open(\"{config}\"));"
    "print(\"npu\" if c.get(\"engine\")==\"npu\" else c.get(\"model\",\"\"))' 2>/dev/null); "
    "TS=$(ls -t {transcripts}/*.txt 2>/dev/null | head -1); "
    'AGE=""; if [ -n "$TS" ]; then AGE=$(( $(date +%s) - $(stat -c %Y "$TS") )); fi; '
    "PEND=$(python3 -c \"from pathlib import Path;c=Path('{chunks}');t=Path('{transcripts}');"
    "print(sum(1 for pat in ('*.wav','*.mp3') for p in c.glob(pat) "
    "if not (t/(p.stem+'.done')).is_file()))\" 2>/dev/null || echo 0); "
    "printf '%s\\n%s\\n%s\\n%s\\n' \"$STATE\" \"$MODEL\" \"$AGE\" \"$PEND\""
)

_REMOTE_PURGE_SCRIPT = (
    "python3 -c \"from pathlib import Path;c=Path('{chunks}');t=Path('{transcripts}');"
    "files=[p for pat in ('*.wav','*.mp3') for p in c.glob(pat) "
    "if not (t/(p.stem+'.done')).is_file()];"
    "[p.unlink() for p in files];print(len(files))\""
)


@dataclass
class OffloadStatus:
    id: str
    label: str
    host: str
    reachable: bool
    forwarder: str
    transcribe: str
    model: Optional[str] = None
    last_caption_age_sec: Optional[int] = None
    pending_chunks: Optional[int] = None
    error: Optional[str] = None

    @property
    def online(self) -> bool:
        return (
            self.reachable
            and self.transcribe == "active"
            and self.forwarder == "active"
        )

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "host": self.host,
            "reachable": self.reachable,
            "online": self.online,
            "forwarder": self.forwarder,
            "transcribe": self.transcribe,
            "model": self.model,
            "last_caption_age_sec": self.last_caption_age_sec,
            "pending_chunks": self.pending_chunks,
            "error": self.error,
        }


@dataclass
class PurgeQueueResult:
    host_id: str
    pi5_deleted: int
    remote_deleted: int
    pi5_pending_before: int
    remote_pending_before: int

    def as_dict(self) -> dict:
        return {
            "host_id": self.host_id,
            "pi5_deleted": self.pi5_deleted,
            "remote_deleted": self.remote_deleted,
            "pi5_pending_before": self.pi5_pending_before,
            "remote_pending_before": self.remote_pending_before,
        }


def _run(cmd: List[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, capture_output=True, text=True, check=False, timeout=timeout
    )


def _forwarder_state(unit: str) -> str:
    try:
        result = _run(["systemctl", "is-active", unit], timeout=4.0)
    except subprocess.TimeoutExpired:
        return "unknown"
    return (result.stdout or result.stderr or "unknown").strip() or "unknown"


def _probe_remote(cfg: OffloadHostConfig) -> tuple[bool, str, Optional[str], Optional[int], Optional[int], Optional[str]]:
    """Returns (reachable, transcribe_state, model, age_sec, pending_chunks, error)."""
    remote = _REMOTE_SCRIPT.format(
        service=cfg.transcribe_service,
        config=cfg.remote_config_path,
        transcripts=cfg.transcripts_dir,
        chunks=cfg.chunks_dir,
    )
    cmd = [
        "ssh",
        "-i", cfg.ssh_key,
        "-p", str(cfg.ssh_port),
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        "-o", "IdentitiesOnly=yes",
        "-o", "ConnectTimeout=3",
        f"{cfg.ssh_user}@{cfg.host}",
        remote,
    ]
    try:
        result = _run(cmd, timeout=15.0)
    except subprocess.TimeoutExpired:
        return False, "unknown", None, None, None, "ssh timeout"
    if result.returncode != 0:
        err = (result.stderr or "ssh failed").strip().splitlines()
        return False, "unknown", None, None, None, (err[-1] if err else "ssh failed")

    lines = (result.stdout or "").splitlines()
    state = lines[0].strip() if len(lines) > 0 else "unknown"
    model = lines[1].strip() if len(lines) > 1 and lines[1].strip() else None
    age: Optional[int] = None
    if len(lines) > 2 and lines[2].strip().lstrip("-").isdigit():
        age = int(lines[2].strip())
    pending: Optional[int] = None
    if len(lines) > 3 and lines[3].strip().isdigit():
        pending = int(lines[3].strip())
    return True, state or "unknown", model, age, pending, None


def _ssh_cmd(cfg: OffloadHostConfig, remote: str) -> List[str]:
    return [
        "ssh",
        "-i", cfg.ssh_key,
        "-p", str(cfg.ssh_port),
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        "-o", "IdentitiesOnly=yes",
        "-o", "ConnectTimeout=3",
        f"{cfg.ssh_user}@{cfg.host}",
        remote,
    ]


def _purge_remote(cfg: OffloadHostConfig) -> int:
    remote = _REMOTE_PURGE_SCRIPT.format(
        chunks=cfg.chunks_dir,
        transcripts=cfg.transcripts_dir,
    )
    cmd = _ssh_cmd(cfg, remote)
    try:
        result = _run(cmd, timeout=120.0)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("ssh timeout while purging remote queue") from exc
    if result.returncode != 0:
        err = (result.stderr or "ssh failed").strip().splitlines()
        raise RuntimeError(err[-1] if err else "ssh purge failed")
    line = (result.stdout or "").strip().splitlines()
    if not line or not line[-1].isdigit():
        raise RuntimeError("unexpected purge response from offload host")
    return int(line[-1])


def purge_queue(cfg: OffloadHostConfig) -> PurgeQueueResult:
    """Drop pending audio chunks on Pi5 and the offload host (keeps .done audit trail)."""
    from orchestrator import whisper_control

    pi5_pending = whisper_control.count_pending_queue()
    remote_pending = _probe_remote(cfg)[4] or 0
    pi5_deleted = whisper_control.purge_pending_queue()
    remote_deleted = _purge_remote(cfg)
    return PurgeQueueResult(
        host_id=cfg.id,
        pi5_deleted=pi5_deleted,
        remote_deleted=remote_deleted,
        pi5_pending_before=pi5_pending,
        remote_pending_before=remote_pending,
    )


def _status_for(cfg: OffloadHostConfig) -> OffloadStatus:
    forwarder = _forwarder_state(cfg.forwarder_service)
    reachable, transcribe, model, age, pending, error = _probe_remote(cfg)
    return OffloadStatus(
        id=cfg.id,
        label=cfg.label,
        host=cfg.host,
        reachable=reachable,
        forwarder=forwarder,
        transcribe=transcribe,
        model=model,
        last_caption_age_sec=age,
        pending_chunks=pending,
        error=error,
    )


def get_status(offload_hosts: List[OffloadHostConfig]) -> List[OffloadStatus]:
    if not offload_hosts:
        return []
    with ThreadPoolExecutor(max_workers=max(2, len(offload_hosts))) as pool:
        return list(pool.map(_status_for, offload_hosts))
