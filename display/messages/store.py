"""Wall-local storage for custom messages, shared by the web API and display worker.

``custom_messages.json`` holds the schedule (normally pushed from the Pi5
orchestrator). ``custom_messages_preview.json`` holds a one-off "show now".
Both live under ``$SPECTRA_DATA_ROOT/config`` and are rewritten atomically
because the display worker polls them while the web API writes.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from display.messages.schema import normalize_message, normalize_messages

STATE_NAME = "custom_messages.json"
PREVIEW_NAME = "custom_messages_preview.json"

_lock = threading.RLock()
_cache: Dict[str, Any] = {"path": None, "mtime": None, "state": None}


def _config_dir() -> Path:
    data_root = Path(os.environ.get("SPECTRA_DATA_ROOT", "/data/spectra"))
    if (data_root / "config").exists() or data_root.exists():
        return data_root / "config"
    return Path(__file__).resolve().parents[2] / "config"


def revision_of(messages: List[Dict[str, Any]]) -> str:
    blob = json.dumps(messages, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


def _empty_state() -> Dict[str, Any]:
    return {"messages": [], "revision": revision_of([]), "updated_at": None}


def _write_atomic(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2)
        fp.write("\n")
    os.replace(tmp, path)


def load_state(path: Optional[Path] = None) -> Dict[str, Any]:
    """Current schedule; cached on mtime so the display loop can call it every pass."""
    path = path or _config_dir() / STATE_NAME
    with _lock:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = None
        if _cache["state"] is not None and _cache["path"] == path and _cache["mtime"] == mtime:
            return _cache["state"]

        state = _empty_state()
        if mtime is not None:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                messages = normalize_messages(raw.get("messages", []))
                state = {
                    "messages": messages,
                    "revision": revision_of(messages),
                    "updated_at": raw.get("updated_at"),
                }
            except (OSError, ValueError):
                pass    # keep showing nothing rather than crash the display loop
        _cache.update(path=path, mtime=mtime, state=state)
        return state


def save_messages(messages: Any, path: Optional[Path] = None) -> Dict[str, Any]:
    """Validate and store a full message list. Raises MessageError on bad input."""
    path = path or _config_dir() / STATE_NAME
    normalized = normalize_messages(messages)
    state = {
        "messages": normalized,
        "revision": revision_of(normalized),
        "updated_at": time.time(),
    }
    with _lock:
        _write_atomic(path, state)
        _cache.update(path=None, mtime=None, state=None)
    return state


def set_preview(message: Any, seconds: Optional[int] = None,
                path: Optional[Path] = None) -> Dict[str, Any]:
    """Show one message immediately, for ``seconds`` (default: its duration)."""
    path = path or _config_dir() / PREVIEW_NAME
    normalized = normalize_message(message)
    shown_for = int(seconds or normalized["duration_seconds"])
    now = time.time()
    payload = {"message": normalized, "started_at": now, "until": now + shown_for}
    with _lock:
        _write_atomic(path, payload)
    return payload


def clear_preview(path: Optional[Path] = None) -> None:
    path = path or _config_dir() / PREVIEW_NAME
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def load_preview(now: Optional[float] = None,
                 path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """The active preview, or None once it has expired."""
    path = path or _config_dir() / PREVIEW_NAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    now = time.time() if now is None else now
    if not isinstance(raw, dict) or float(raw.get("until", 0)) <= now:
        clear_preview(path)     # so later passes stop at a cheap failed open()
        return None
    return raw
