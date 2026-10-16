"""Per-device LED matrix geometry and timing, without importing rgbmatrix.

Defaults are the Spectra walls (9 × 64×64, Electrodragon, Rotate:270), so the
walls need no config file. Other devices (Mini-Spectra Clock) put overrides in
``$SPECTRA_DATA_ROOT/config/matrix.local.json``, e.g. one 64×64 panel on an
Adafruit HAT::

    {"chain_length": 1, "parallel": 1, "hardware_mapping": "adafruit-hat",
     "pixel_mapper": "", "max_brightness": 90}

Read once at import; the display process restarts to pick up changes.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

DATA_ROOT = os.environ.get("SPECTRA_DATA_ROOT", "/data/spectra")
CONFIG_NAME = "matrix.local.json"


@dataclass(frozen=True)
class VideoTiming:
    """video-viewer flags that differ from the in-process display on the walls."""

    gpio_slowdown: int = 4
    pwm_bits: int = 9
    scan_mode: int = 1


@dataclass(frozen=True)
class MatrixConfig:
    panel_rows: int = 64
    panel_cols: int = 64
    chain_length: int = 3
    parallel: int = 3
    hardware_mapping: str = "regular"
    pixel_mapper: str = "Rotate:270"
    gpio_slowdown: int = 5
    pwm_bits: int = 10
    pwm_lsb_nanoseconds: int = 50
    limit_refresh_hz: int = 0
    # Ceiling on every brightness the schedule asks for (1-100).
    max_brightness: int = 100
    # Only needed when the pixel mapper changes the shape in a way not derived
    # below (e.g. a custom Remap); otherwise computed from the geometry.
    canvas_width: Optional[int] = None
    canvas_height: Optional[int] = None
    video: VideoTiming = field(default_factory=VideoTiming)

    @property
    def canvas_size(self) -> Tuple[int, int]:
        if self.canvas_width and self.canvas_height:
            return self.canvas_width, self.canvas_height
        remap = re.match(r"Remap:(\d+),(\d+)", self.pixel_mapper or "")
        if remap:
            return int(remap.group(1)), int(remap.group(2))
        width = self.panel_cols * self.chain_length
        height = self.panel_rows * self.parallel
        if "U-mapper" in (self.pixel_mapper or ""):     # chain folded in half, e.g. 2×2
            width, height = width // 2, height * 2
        rotate = re.search(r"Rotate:(\d+)", self.pixel_mapper or "")
        if rotate and int(rotate.group(1)) % 180 == 90:
            width, height = height, width
        return width, height

    def clamp_brightness(self, value: int) -> int:
        return max(1, min(int(self.max_brightness), int(value)))


def _config_paths() -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    return [Path(DATA_ROOT) / "config" / CONFIG_NAME, root / "config" / CONFIG_NAME]


def parse_config(raw: Dict[str, Any]) -> MatrixConfig:
    known = {f.name for f in fields(MatrixConfig)} - {"video"}
    unknown = set(raw) - known - {"video"}
    if unknown:
        raise ValueError(f"unknown matrix config keys: {', '.join(sorted(unknown))}")
    video = VideoTiming(**(raw.get("video") or {}))
    cfg = MatrixConfig(**{k: v for k, v in raw.items() if k in known}, video=video)
    if not 1 <= cfg.max_brightness <= 100:
        raise ValueError("max_brightness must be 1-100")
    return cfg


def load_matrix_config() -> MatrixConfig:
    for path in _config_paths():
        if path.is_file():
            return parse_config(json.loads(path.read_text(encoding="utf-8")))
    return MatrixConfig()


MATRIX = load_matrix_config()
CANVAS_W, CANVAS_H = MATRIX.canvas_size
