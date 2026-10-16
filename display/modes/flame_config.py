"""Shared Galactic Unicorn fire config: flame vs lava profiles.

Themes, intensity height caps, and per-profile physics / output gain.
See LICENSE.md for Pimoroni attribution.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Tuple

import numpy as np

from display.matrix_config import CANVAS_H
from display.modes.color_rotate import color_rotate_api_fields

Color = Tuple[int, int, int]
FireProfile = Literal["flame", "lava"]

_GALACTIC_REF_HEIGHT = 11
_GALACTIC_REF_DAMPING = 0.97

DEFAULT_EMBER: Color = (20, 20, 20)
DEFAULT_BLACK: Color = (0, 0, 0)

FIRE_THEMES: Dict[str, Dict[str, Color]] = {
    "orange": {
        "core": (180, 30, 0),
        "mid": (220, 160, 0),
        "tip": (255, 255, 180),
    },
    "red": {
        "core": (200, 0, 0),
        "mid": (255, 50, 0),
        "tip": (255, 200, 120),
    },
    "yellow": {
        "core": (200, 120, 0),
        "mid": (255, 200, 0),
        "tip": (255, 255, 200),
    },
    "blue": {
        "core": (0, 40, 180),
        "mid": (40, 120, 255),
        "tip": (180, 220, 255),
    },
    "green": {
        "core": (0, 120, 40),
        "mid": (60, 200, 80),
        "tip": (180, 255, 200),
    },
    "purple": {
        "core": (80, 0, 160),
        "mid": (160, 40, 220),
        "tip": (220, 180, 255),
    },
    "cyan": {
        "core": (0, 140, 160),
        "mid": (0, 220, 255),
        "tip": (180, 255, 255),
    },
    "magenta": {
        "core": (160, 0, 120),
        "mid": (220, 0, 180),
        "tip": (255, 180, 240),
    },
    "white": {
        "core": (120, 120, 140),
        "mid": (200, 200, 220),
        "tip": (255, 255, 255),
    },
}

# Back-compat aliases used by web/API imports.
FLAME_THEMES = FIRE_THEMES
FLAME_PRESETS = FIRE_THEMES
DEFAULT_FLAME_PRESET = "orange"
DEFAULT_FLAME_INTENSITY = 0
FLAME_PANEL_ROWS = 3
FIRE_PANEL_ROWS = 3

# Night intensity: 1.5 panel rows tall, heavily dimmed.
_NIGHT_HEIGHT_PANELS = 1.5
_NIGHT_OUTPUT_GAIN = 0.10

# Lava = archived dense heat look; flame = sparser tongues.
_PROFILES: Dict[str, Dict[str, Any]] = {
    "lava": {
        # Snapshot of the pre-split dense sim (PSU-friendly gain at non-night).
        "damping": (0.990, 0.993, 0.996, 0.998),
        "seed_heat": (0.85, 1.0, 1.25, 1.5),
        "turbulence": (0.04, 0.05, 0.06, 0.08),
        "heat_scale": (220, 200, 185, 170),
        "seed_density": (1.0, 1.0, 1.0, 1.0),
        "palette_bounds": (0.0, 0.06, 0.14, 0.30, 0.52, 1.0),
        "day_output_gain": 0.70,
    },
    "flame": {
        # Lower fill, more flicker / broken columns.
        "damping": (0.985, 0.988, 0.992, 0.995),
        "seed_heat": (1.0, 1.15, 1.35, 1.55),
        "turbulence": (0.09, 0.11, 0.13, 0.15),
        "heat_scale": (170, 155, 145, 135),
        "seed_density": (0.22, 0.28, 0.34, 0.40),
        "palette_bounds": (0.0, 0.10, 0.22, 0.40, 0.62, 1.0),
        "day_output_gain": 0.90,
    },
}


def _profile(name: str) -> Dict[str, Any]:
    return _PROFILES.get(name, _PROFILES["flame"])


def resolve_fire_intensity(config: Optional[dict]) -> int:
    cfg = dict(config or {})
    try:
        value = int(cfg.get("intensity", DEFAULT_FLAME_INTENSITY))
    except (TypeError, ValueError):
        return DEFAULT_FLAME_INTENSITY
    return max(0, min(FIRE_PANEL_ROWS, value))


def resolve_flame_intensity(config: Optional[dict]) -> int:
    return resolve_fire_intensity(config)


def resolve_fire_height_px(
    intensity: int,
    display_h: int,
    *,
    panel_rows: int = FIRE_PANEL_ROWS,
) -> int:
    """Visible heat height from the bottom edge (px). Night = 1.5 panel rows."""
    intensity = max(0, min(panel_rows, intensity))
    panel_px = max(1, display_h // panel_rows)
    if intensity == 0:
        return max(16, int(round(panel_px * _NIGHT_HEIGHT_PANELS)))
    return min(display_h, intensity * panel_px)


def resolve_flame_height_px(
    intensity: int,
    display_h: int,
    *,
    panel_rows: int = FIRE_PANEL_ROWS,
) -> int:
    return resolve_fire_height_px(intensity, display_h, panel_rows=panel_rows)


def resolve_fire_output_gain(profile: FireProfile, intensity: int) -> float:
    """Pixel RGB multiplier after LUT (night dim + lava PSU relief)."""
    intensity = max(0, min(FIRE_PANEL_ROWS, intensity))
    if intensity == 0:
        return _NIGHT_OUTPUT_GAIN
    return float(_profile(profile)["day_output_gain"])


def _height_scaled_damping(display_h: int) -> float:
    loss = 1.0 - _GALACTIC_REF_DAMPING
    scaled_loss = loss * (_GALACTIC_REF_HEIGHT / max(1, display_h))
    return 1.0 - scaled_loss


def resolve_fire_damping(
    profile: FireProfile,
    intensity: int,
    display_h: int,
    base: float = 0.97,
) -> float:
    intensity = max(0, min(FIRE_PANEL_ROWS, intensity))
    tier = float(_profile(profile)["damping"][intensity])
    scaled = _height_scaled_damping(display_h)
    auto = min(0.9998, max(tier, scaled))
    if base != 0.97 and base >= 0.99:
        return min(0.9998, max(auto, base))
    return auto


def resolve_flame_damping(
    intensity: int,
    display_h: int,
    base: float = 0.97,
) -> float:
    return resolve_fire_damping("flame", intensity, display_h, base)


def resolve_fire_seed_heat(profile: FireProfile, intensity: int) -> float:
    intensity = max(0, min(FIRE_PANEL_ROWS, intensity))
    return float(_profile(profile)["seed_heat"][intensity])


def resolve_flame_seed_heat(intensity: int) -> float:
    return resolve_fire_seed_heat("flame", intensity)


def resolve_fire_turbulence(profile: FireProfile, intensity: int) -> float:
    intensity = max(0, min(FIRE_PANEL_ROWS, intensity))
    return float(_profile(profile)["turbulence"][intensity])


def resolve_flame_turbulence(intensity: int) -> float:
    return resolve_fire_turbulence("flame", intensity)


def resolve_fire_heat_scale(profile: FireProfile, intensity: int) -> float:
    intensity = max(0, min(FIRE_PANEL_ROWS, intensity))
    return float(_profile(profile)["heat_scale"][intensity])


def resolve_flame_heat_scale(intensity: int) -> float:
    return resolve_fire_heat_scale("flame", intensity)


def resolve_fire_seed_density(profile: FireProfile, intensity: int) -> float:
    intensity = max(0, min(FIRE_PANEL_ROWS, intensity))
    return float(_profile(profile)["seed_density"][intensity])


def build_fire_palette_lut(
    palette: List[Color],
    *,
    profile: FireProfile = "flame",
) -> np.ndarray:
    """256×3 RGB LUT with smooth interpolation across palette stops."""
    stops = np.array(palette, dtype=np.float32)
    bounds = np.array(_profile(profile)["palette_bounds"], dtype=np.float32)
    lut = np.zeros((256, 3), dtype=np.uint8)
    for i in range(256):
        value = i / 255.0
        seg = min(4, max(0, int(np.searchsorted(bounds, value, side="right") - 1)))
        span = bounds[seg + 1] - bounds[seg]
        t = (value - bounds[seg]) / span if span > 0 else 0.0
        lut[i] = (stops[seg] * (1.0 - t) + stops[min(seg + 1, 4)] * t).astype(np.uint8)
    return lut


def build_flame_palette_lut(palette: List[Color]) -> np.ndarray:
    return build_fire_palette_lut(palette, profile="flame")


def _clamp_rgb(value: Any) -> Optional[Color]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        return tuple(max(0, min(255, int(c))) for c in value)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def resolve_fire_stops(config: Optional[dict]) -> Dict[str, Color]:
    cfg = dict(config or {})
    preset_name = cfg.get("preset")
    if isinstance(preset_name, str) and preset_name in FIRE_THEMES:
        theme = dict(FIRE_THEMES[preset_name])
    else:
        theme = dict(FIRE_THEMES[DEFAULT_FLAME_PRESET])

    for key in ("core", "mid", "tip", "ember"):
        override = _clamp_rgb(cfg.get(key))
        if override is not None:
            theme[key] = override

    if "ember" not in theme:
        theme["ember"] = DEFAULT_EMBER
    return theme


def resolve_flame_stops(config: Optional[dict]) -> Dict[str, Color]:
    return resolve_fire_stops(config)


def resolve_fire_palette(config: Optional[dict]) -> List[Color]:
    stops = resolve_fire_stops(config)
    return [
        DEFAULT_BLACK,
        stops["ember"],
        stops["core"],
        stops["mid"],
        stops["tip"],
    ]


def resolve_flame_palette(config: Optional[dict]) -> List[Color]:
    return resolve_fire_palette(config)


def resolve_flame_color(config: Optional[dict]) -> Color:
    return resolve_fire_stops(config)["core"]


def fire_config_for_api(profile: FireProfile, config: Optional[dict]) -> Dict[str, Any]:
    stops = resolve_fire_stops(config)
    cfg = dict(config or {})
    preset = cfg.get("preset") if isinstance(cfg.get("preset"), str) else None
    intensity = resolve_fire_intensity(cfg)
    canvas_h = CANVAS_H
    height_px = resolve_fire_height_px(intensity, canvas_h)
    return {
        "profile": profile,
        "preset": preset,
        "intensity": intensity,
        "panel_rows": FIRE_PANEL_ROWS,
        "height_px": height_px,
        "output_gain": round(resolve_fire_output_gain(profile, intensity), 3),
        "damping": round(resolve_fire_damping(profile, intensity, canvas_h), 4),
        "core": list(stops["core"]),
        "mid": list(stops["mid"]),
        "tip": list(stops["tip"]),
        "ember": list(stops["ember"]),
        "colors": [list(c) for c in resolve_fire_palette(config)],
        "presets": list(FIRE_THEMES.keys()),
        **color_rotate_api_fields(cfg),
    }


def flame_config_for_api(config: Optional[dict]) -> Dict[str, Any]:
    return fire_config_for_api("flame", config)


def lava_config_for_api(config: Optional[dict]) -> Dict[str, Any]:
    return fire_config_for_api("lava", config)
