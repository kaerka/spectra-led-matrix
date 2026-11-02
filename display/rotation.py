"""Auto-rotate: switch this display to a random mode from a pool on a timer.

Settings live in ``config/rotation.json`` (one file per Pi, so each panel group
rotates on its own). The display worker drives the switching; any manual mode
or setting change restarts the countdown because it bumps the state's
``updated_at``.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from display.modes.registry import MODES
from display.state import ROOT, DisplayState, set_active_mode

ROTATION_PATH = os.path.join(ROOT, "config", "rotation.json")

INTERVALS = (60, 120, 300, 600, 900, 1800, 3600)
DEFAULT_INTERVAL = 300
# media hands off to the video player; gibson is unfinished (placeholder
# textures, ~5 fps on a Pi 4).
NEVER_ROTATE = frozenset({"media", "gibson"})
# Off by default in the pool: they are information screens, not animations.
NOT_ANIMATIONS = frozenset({"weather", "world_clock", "analog_clock"})

_lock = threading.RLock()
_cache: dict = {"mtime": None, "settings": None}


def rotatable_modes() -> List[str]:
    return [m for m in MODES if m not in NEVER_ROTATE]


def default_pool() -> List[str]:
    return [m for m in rotatable_modes() if m not in NOT_ANIMATIONS]


@dataclass
class RotationSettings:
    enabled: bool = False
    interval_s: int = DEFAULT_INTERVAL
    modes: List[str] = field(default_factory=default_pool)
    updated_at: float = 0.0

    def pool(self) -> List[str]:
        valid = set(rotatable_modes())
        return [m for m in self.modes if m in valid]


def _from_raw(raw: Any) -> RotationSettings:
    s = RotationSettings()
    if not isinstance(raw, dict):
        return s
    s.enabled = bool(raw.get("enabled", False))
    if raw.get("interval_s") in INTERVALS:
        s.interval_s = int(raw["interval_s"])
    if isinstance(raw.get("modes"), list):
        s.modes = [m for m in raw["modes"] if isinstance(m, str)]
    if isinstance(raw.get("updated_at"), (int, float)):
        s.updated_at = float(raw["updated_at"])
    return s


def load_rotation(path: str = ROTATION_PATH) -> RotationSettings:
    with _lock:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return RotationSettings()
        if _cache["settings"] is not None and _cache["mtime"] == mtime and _cache.get("path") == path:
            return _cache["settings"]
        try:
            with open(path, encoding="utf-8") as fp:
                settings = _from_raw(json.load(fp))
        except (OSError, ValueError):
            settings = RotationSettings()
        _cache.update(path=path, mtime=mtime, settings=settings)
        return settings


def save_rotation(settings: RotationSettings, path: str = ROTATION_PATH) -> RotationSettings:
    settings.updated_at = time.time()
    with _lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(asdict(settings), fp, indent=2)
            fp.write("\n")
        os.replace(tmp, path)
        _cache.update(path=path, mtime=os.path.getmtime(path), settings=settings)
    return settings


def update_rotation(patch: Any, path: str = ROTATION_PATH) -> RotationSettings:
    """Apply a PUT body; raises ValueError with a user-facing message."""
    if not isinstance(patch, dict) or not patch:
        raise ValueError("Provide enabled, interval_s, and/or modes")
    current = load_rotation(path)
    s = RotationSettings(current.enabled, current.interval_s, list(current.modes))
    for key, value in patch.items():
        if key == "enabled":
            if not isinstance(value, bool):
                raise ValueError("enabled must be true or false")
            s.enabled = value
        elif key == "interval_s":
            if value not in INTERVALS:
                raise ValueError(f"interval_s must be one of {list(INTERVALS)}")
            s.interval_s = int(value)
        elif key == "modes":
            if not isinstance(value, list) or not all(isinstance(m, str) for m in value):
                raise ValueError("modes must be a list of mode ids")
            unknown = [m for m in value if m not in rotatable_modes()]
            if unknown:
                raise ValueError(f"Cannot rotate through: {', '.join(unknown)}")
            if len(set(value)) < 2:
                raise ValueError("Pick at least two modes to rotate through")
            s.modes = [m for m in rotatable_modes() if m in value]
        else:
            raise ValueError(f"Unknown setting {key!r}")
    return save_rotation(s, path)


def next_switch_at(settings: RotationSettings, state: DisplayState) -> Optional[float]:
    if not settings.enabled or len(settings.pool()) < 2:
        return None
    return max(state.updated_at or 0.0, settings.updated_at) + settings.interval_s


def _interval_label(seconds: int) -> str:
    return f"{seconds // 3600} hr" if seconds >= 3600 else f"{seconds // 60} min"


def rotation_for_api(state: DisplayState, path: str = ROTATION_PATH) -> Dict[str, Any]:
    s = load_rotation(path)
    nxt = next_switch_at(s, state)
    return {
        "enabled": s.enabled,
        "interval_s": s.interval_s,
        "intervals": [{"seconds": i, "label": _interval_label(i)} for i in INTERVALS],
        "modes": s.pool(),
        "available": [{"id": m, "label": MODES[m].label} for m in rotatable_modes()],
        "default_modes": default_pool(),
        "active_mode": state.active_mode,
        "next_switch_at": nxt,
        "seconds_left": None if nxt is None else max(0, round(nxt - time.time())),
    }


class Rotator:
    """Used by the display worker: picks the next mode from a shuffled bag."""

    def __init__(self, path: str = ROTATION_PATH, rng: Optional[random.Random] = None) -> None:
        self.path = path
        self.rng = rng or random.Random()
        self._bag: List[str] = []

    def _draw(self, pool: List[str], current: str) -> str:
        self._bag = [m for m in self._bag if m in pool]
        if not self._bag:
            self._bag = list(pool)
            self.rng.shuffle(self._bag)
        pick = self._bag.pop()
        if pick == current:
            if not self._bag:
                self._bag = [m for m in pool if m != current]
                self.rng.shuffle(self._bag)
            self._bag.insert(0, pick)
            pick = self._bag.pop()
        return pick

    def maybe_rotate(self, state: DisplayState, now: Optional[float] = None) -> Optional[str]:
        """Switch modes if the timer ran out; returns the new mode id, else None."""
        settings = load_rotation(self.path)
        due = next_switch_at(settings, state)
        if due is None or (now if now is not None else time.time()) < due:
            return None
        pick = self._draw(settings.pool(), state.active_mode)
        set_active_mode(pick)
        return pick
