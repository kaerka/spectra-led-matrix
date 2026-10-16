"""Starfield (Win95-style fly-through) config — shared by mode + web API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from display.modes.color_rotate import color_rotate_api_fields

Color = Tuple[int, int, int]

DEFAULT_STARFIELD_INTENSITY = 0
STARFIELD_PANEL_ROWS = 3  # intensity 0–3, same knob shape as fire modes

# Color modes: how RGB is chosen per star / depth.
COLOR_MODES = (
    "white",
    "warm",
    "cool",
    "rainbow",
    "depth",
    "dual",
)
DEFAULT_COLOR_MODE = "depth"

# Named palettes for dual / depth / single-tint modes (near, mid, far-ish).
STARFIELD_THEMES: Dict[str, Dict[str, Color]] = {
    "classic": {
        "near": (255, 255, 255),
        "mid": (200, 210, 255),
        "far": (120, 140, 200),
    },
    "warm": {
        "near": (255, 240, 200),
        "mid": (255, 180, 80),
        "far": (180, 60, 20),
    },
    "cool": {
        "near": (220, 240, 255),
        "mid": (80, 160, 255),
        "far": (20, 40, 120),
    },
    "neon": {
        "near": (255, 80, 255),
        "mid": (80, 255, 200),
        "far": (40, 80, 200),
    },
    "ember": {
        "near": (255, 220, 160),
        "mid": (255, 100, 20),
        "far": (80, 20, 10),
    },
    "aurora": {
        "near": (180, 255, 220),
        "mid": (80, 220, 160),
        "far": (40, 60, 140),
    },
}

DEFAULT_THEME = "classic"
STARFIELD_PRESETS = STARFIELD_THEMES

# Per-intensity: star count, flight speed, output gain, max star radius (px).
_COUNT_BY_INTENSITY = (48, 120, 220, 360)
_SPEED_BY_INTENSITY = (0.55, 1.0, 1.55, 2.2)
_GAIN_BY_INTENSITY = (0.18, 0.75, 0.90, 1.0)
_MAX_RADIUS_BY_INTENSITY = (1.2, 1.8, 2.4, 3.0)
_TRAIL_BY_INTENSITY = (0, 1, 1, 2)  # extra pixels behind motion


def resolve_starfield_intensity(config: Optional[dict]) -> int:
    cfg = dict(config or {})
    try:
        value = int(cfg.get("intensity", DEFAULT_STARFIELD_INTENSITY))
    except (TypeError, ValueError):
        return DEFAULT_STARFIELD_INTENSITY
    return max(0, min(STARFIELD_PANEL_ROWS, value))


def resolve_color_mode(config: Optional[dict]) -> str:
    cfg = dict(config or {})
    mode = cfg.get("color_mode", DEFAULT_COLOR_MODE)
    if isinstance(mode, str) and mode in COLOR_MODES:
        return mode
    return DEFAULT_COLOR_MODE


def resolve_theme_name(config: Optional[dict]) -> str:
    cfg = dict(config or {})
    name = cfg.get("preset")
    if isinstance(name, str) and name in STARFIELD_THEMES:
        return name
    return DEFAULT_THEME


def _clamp_rgb(value: Any) -> Optional[Color]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        return tuple(max(0, min(255, int(c))) for c in value)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def resolve_starfield_stops(config: Optional[dict]) -> Dict[str, Color]:
    cfg = dict(config or {})
    theme = dict(STARFIELD_THEMES[resolve_theme_name(cfg)])
    for key in ("near", "mid", "far"):
        override = _clamp_rgb(cfg.get(key))
        if override is not None:
            theme[key] = override
    return theme


def resolve_star_count(intensity: int) -> int:
    intensity = max(0, min(STARFIELD_PANEL_ROWS, intensity))
    return int(_COUNT_BY_INTENSITY[intensity])


def resolve_speed(intensity: int) -> float:
    intensity = max(0, min(STARFIELD_PANEL_ROWS, intensity))
    return float(_SPEED_BY_INTENSITY[intensity])


def resolve_output_gain(intensity: int) -> float:
    intensity = max(0, min(STARFIELD_PANEL_ROWS, intensity))
    return float(_GAIN_BY_INTENSITY[intensity])


def resolve_max_radius(intensity: int) -> float:
    intensity = max(0, min(STARFIELD_PANEL_ROWS, intensity))
    return float(_MAX_RADIUS_BY_INTENSITY[intensity])


def resolve_trail(intensity: int) -> int:
    intensity = max(0, min(STARFIELD_PANEL_ROWS, intensity))
    return int(_TRAIL_BY_INTENSITY[intensity])


def starfield_config_for_api(config: Optional[dict]) -> Dict[str, Any]:
    cfg = dict(config or {})
    intensity = resolve_starfield_intensity(cfg)
    stops = resolve_starfield_stops(cfg)
    preset = cfg.get("preset") if isinstance(cfg.get("preset"), str) else None
    if preset not in STARFIELD_THEMES:
        preset = resolve_theme_name(cfg)
    return {
        "preset": preset,
        "color_mode": resolve_color_mode(cfg),
        "color_modes": list(COLOR_MODES),
        "intensity": intensity,
        "panel_rows": STARFIELD_PANEL_ROWS,
        "star_count": resolve_star_count(intensity),
        "speed": round(resolve_speed(intensity), 2),
        "output_gain": round(resolve_output_gain(intensity), 3),
        "near": list(stops["near"]),
        "mid": list(stops["mid"]),
        "far": list(stops["far"]),
        "presets": list(STARFIELD_THEMES.keys()),
        **color_rotate_api_fields(cfg),
    }
