"""Time-of-day brightness schedule for the LED matrix."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from zoneinfo import ZoneInfo

from display.matrix_config import MATRIX

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "timezone": "America/New_York",
    "check_interval_seconds": 30,
    "steps": [
        {"time": "06:00", "brightness": 80},
        {"time": "07:00", "brightness": 100},
        {"time": "22:00", "brightness": 50},
        {"time": "23:00", "brightness": 20},
    ],
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _config_paths() -> list[Path]:
    data_root = os.environ.get("SPECTRA_DATA_ROOT", "/data/spectra")
    root = _repo_root()
    return [
        Path(data_root) / "config" / "brightness_schedule.local.json",
        root / "config" / "brightness_schedule.local.json",
        root / "config" / "brightness_schedule.example.json",
    ]


def _parse_time_minutes(value: str) -> int:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time {value!r}, expected HH:MM")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid time {value!r}")
    return hour * 60 + minute


class BrightnessSchedule:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.enabled = bool(cfg.get("enabled", True))
        self.timezone = ZoneInfo(str(cfg.get("timezone", "America/New_York")))
        self.check_interval = float(cfg.get("check_interval_seconds", 30))
        raw_steps = cfg.get("steps") or DEFAULTS["steps"]
        self.steps = sorted(
            (_parse_time_minutes(str(step["time"])), int(step["brightness"]))
            for step in raw_steps
        )
        if not self.steps:
            raise ValueError("brightness schedule requires at least one step")
        for _, level in self.steps:
            if not 1 <= level <= 100:
                raise ValueError(f"brightness must be 1-100, got {level}")
        self._last_target: int | None = None
        self._last_check = 0.0

    @classmethod
    def load_from_config(cls) -> BrightnessSchedule:
        cfg = dict(DEFAULTS)
        for path in _config_paths():
            if path.is_file():
                with open(path, encoding="utf-8") as fh:
                    cfg.update(json.load(fh))
                break
        return cls(cfg)

    def target_brightness(self, now: datetime | None = None) -> int:
        return MATRIX.clamp_brightness(self._scheduled(now))

    def _scheduled(self, now: datetime | None = None) -> int:
        if not self.enabled:
            return 100
        now = now or datetime.now(self.timezone)
        if now.tzinfo is None:
            now = now.replace(tzinfo=self.timezone)
        else:
            now = now.astimezone(self.timezone)
        cur_min = now.hour * 60 + now.minute
        brightness = self.steps[-1][1]
        for mins, level in self.steps:
            if mins <= cur_min:
                brightness = level
        return brightness

    def initial_brightness(self) -> int:
        target = self.target_brightness()
        self._last_target = target
        return target

    def apply_if_needed(self, matrix) -> bool:
        """Set matrix brightness when the schedule target changes."""
        now_mono = time.monotonic()
        if (
            self._last_target is not None
            and (now_mono - self._last_check) < self.check_interval
        ):
            return False
        self._last_check = now_mono
        target = self.target_brightness()
        if self._last_target == target:
            return False
        self._last_target = target
        if matrix is not None:
            matrix.brightness = target
            print(f"[brightness] schedule → {target}%", flush=True)
        return True


def scheduled_brightness() -> int:
    """Current schedule target (for video-viewer subprocess argv)."""
    return BrightnessSchedule.load_from_config().target_brightness()
