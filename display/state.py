"""Persisted display state (active mode) shared between web UI and runner."""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
DEFAULT_STATE_PATH = os.path.join(ROOT, "config", "display_state.json")
EXAMPLE_STATE_PATH = os.path.join(ROOT, "config", "display_state.example.json")

DEFAULT_MODE = "weather"
_lock = threading.RLock()
_cache: dict = {"mtime": 0.0, "state": None}


@dataclass
class DisplayState:
    active_mode: str = DEFAULT_MODE
    media_path: Optional[str] = None
    mode_config: Optional[Dict[str, Any]] = None
    updated_at: Optional[float] = None


def _ensure_state_file(path: str = DEFAULT_STATE_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.isfile(path):
        return
    if os.path.isfile(EXAMPLE_STATE_PATH):
        with open(EXAMPLE_STATE_PATH, encoding="utf-8") as src:
            data = json.load(src)
    else:
        data = asdict(DisplayState())
    with open(path, "w", encoding="utf-8") as dst:
        json.dump(data, dst, indent=2)
        dst.write("\n")


def load_state(path: str = DEFAULT_STATE_PATH) -> DisplayState:
    with _lock:
        _ensure_state_file(path)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0.0
        if _cache["state"] is not None and mtime == _cache["mtime"]:
            return _cache["state"]

        with open(path, encoding="utf-8") as fp:
            raw = json.load(fp)
        state = DisplayState(
            active_mode=raw.get("active_mode") or DEFAULT_MODE,
            media_path=raw.get("media_path"),
            mode_config=raw.get("mode_config") if isinstance(raw.get("mode_config"), dict) else None,
            updated_at=raw.get("updated_at"),
        )
        _cache["state"] = state
        _cache["mtime"] = mtime
        return state


def save_state(state: DisplayState, path: str = DEFAULT_STATE_PATH) -> DisplayState:
    state.updated_at = time.time()
    with _lock:
        _ensure_state_file(path)
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(asdict(state), fp, indent=2)
            fp.write("\n")
        try:
            _cache["mtime"] = os.path.getmtime(path)
        except OSError:
            _cache["mtime"] = time.time()
        _cache["state"] = state
    return state


def set_active_mode(
    mode_id: str,
    *,
    media_path: Optional[str] = None,
    path: str = DEFAULT_STATE_PATH,
) -> DisplayState:
    current = load_state(path)
    if media_path is not None:
        resolved_media = media_path
    elif mode_id == "media":
        resolved_media = current.media_path
    else:
        resolved_media = None
    return save_state(
        DisplayState(
            active_mode=mode_id,
            media_path=resolved_media,
            mode_config=current.mode_config,
        ),
        path,
    )


def set_media_path(media_path: str, path: str = DEFAULT_STATE_PATH) -> DisplayState:
    current = load_state(path)
    return save_state(
        DisplayState(
            active_mode="media",
            media_path=media_path,
            mode_config=current.mode_config,
        ),
        path,
    )


def set_mode_config(
    mode_id: str,
    config: Dict[str, Any],
    *,
    path: str = DEFAULT_STATE_PATH,
) -> DisplayState:
    current = load_state(path)
    all_cfg: Dict[str, Any] = dict(current.mode_config or {})
    merged = dict(all_cfg.get(mode_id) or {})
    if "preset" in config:
        merged.pop("color", None)
        if mode_id in ("flame", "lava"):
            for key in ("core", "mid", "tip", "ember"):
                merged.pop(key, None)
        if mode_id == "starfield":
            for key in ("near", "mid", "far"):
                merged.pop(key, None)
    if "core" in config or "mid" in config or "tip" in config or "ember" in config:
        if mode_id in ("flame", "lava"):
            merged.pop("preset", None)
    if mode_id == "starfield" and (
        "near" in config or "mid" in config or "far" in config
    ):
        merged.pop("preset", None)
    if mode_id == "matrix_rain" and "color" in config:
        merged.pop("preset", None)
    # Procedural effects (effect_config): a palette and custom colours exclude each other.
    if "palette" in config:
        merged.pop("colors", None)
    if "colors" in config:
        merged.pop("palette", None)
    merged.update(config)
    all_cfg[mode_id] = merged
    return save_state(
        DisplayState(
            active_mode=current.active_mode,
            media_path=current.media_path,
            mode_config=all_cfg,
        ),
        path,
    )
