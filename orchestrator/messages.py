"""Custom messages master copy on the Pi5.

The Pi5 keeps the full list, pushes each wall the messages addressed to it
(walls then schedule locally, so they keep showing messages if the Pi5 is
down), and publishes the full list retained over MQTT for small boards that
will schedule locally from it.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import paho.mqtt.client as mqtt

from display.messages.schema import for_target, normalize_messages
from display.messages.store import revision_of

MASTER_NAME = "custom_messages_master.json"
_lock = threading.RLock()


def master_path() -> Path:
    data_root = Path(os.environ.get("SPECTRA_DATA_ROOT", "/data/spectra"))
    if data_root.exists():
        return data_root / "config" / MASTER_NAME
    return Path(__file__).resolve().parents[1] / "config" / MASTER_NAME


def load_master(path: Optional[Path] = None) -> Dict[str, Any]:
    path = path or master_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        messages = normalize_messages(raw.get("messages", []))
        updated_at = raw.get("updated_at")
    except (OSError, ValueError):
        messages, updated_at = [], None
    return {"messages": messages, "revision": revision_of(messages), "updated_at": updated_at}


def save_master(messages: Any, path: Optional[Path] = None) -> Dict[str, Any]:
    """Validate and store the full list. Raises MessageError on bad input."""
    path = path or master_path()
    normalized = normalize_messages(messages)
    state = {"messages": normalized, "revision": revision_of(normalized), "updated_at": time.time()}
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    return state


def wall_revision(messages: List[Dict[str, Any]], host_id: str) -> str:
    """The revision a wall reports once it holds its share of the list."""
    return revision_of(for_target(messages, host_id))


def publish(broker: str, port: int, topic: str, payload: Dict[str, Any],
            retain: bool) -> None:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    try:
        client.connect(broker, port, 30)
        client.loop_start()
        info = client.publish(topic, json.dumps(payload, separators=(",", ":")),
                              qos=1, retain=retain)
        info.wait_for_publish(timeout=3.0)
    finally:
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass


def config_payload(state: Dict[str, Any], timezone: str) -> Dict[str, Any]:
    return {
        "revision": state["revision"],
        "timezone": timezone,
        "updated_at": state["updated_at"],
        "messages": state["messages"],
    }


class WallResync:
    """Background loop that re-pushes the list to walls that missed an update."""

    def __init__(self, check: Callable[[], None], interval: float = 60.0) -> None:
        self._check = check
        self._interval = interval
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="messages-resync", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._check()
            except Exception as exc:
                print(f"[messages] resync failed: {exc}", flush=True)
