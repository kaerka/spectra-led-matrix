"""Gibson / Neuromancer matrix config — shared by mode + web API.

HUB75 blues read dim and photograph magenta on Iris; default *ice* is
green-weighted cyan so the wall and the camera agree.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

Color = Tuple[int, int, int]

DEFAULT_GIBSON_INTENSITY = 2
GIBSON_PANEL_ROWS = 3  # intensity 0–3, same knob shape as fire / starfield

# Semantic stops: grid lines, ICE constructs, bright nodes / packets.
GIBSON_THEMES: Dict[str, Dict[str, Color]] = {
    "ice": {
        "grid": (24, 230, 168),
        "ice": (90, 255, 220),
        "node": (230, 255, 245),
    },
    "phosphor": {
        "grid": (12, 220, 48),
        "ice": (50, 255, 96),
        "node": (210, 255, 190),
    },
    "wintermute": {
        "grid": (70, 170, 230),
        "ice": (150, 210, 255),
        "node": (235, 245, 255),
    },
    "chrome": {
        "grid": (170, 190, 220),
        "ice": (255, 70, 150),
        "node": (255, 255, 255),
    },
    "tessier": {
        "grid": (190, 100, 24),
        "ice": (255, 186, 64),
        "node": (255, 236, 190),
    },
}

DEFAULT_THEME = "ice"
GIBSON_PRESETS = GIBSON_THEMES

# Per-intensity: flight speed, output gain, grid density, ICE count, packets.
_SPEED_BY_INTENSITY = (0.35, 0.75, 1.15, 1.7)
_GAIN_BY_INTENSITY = (0.16, 0.72, 0.90, 1.0)
_X_LINES_BY_INTENSITY = (7, 11, 15, 19)
_ICE_COUNT_BY_INTENSITY = (2, 5, 8, 12)
_PACKET_COUNT_BY_INTENSITY = (2, 5, 8, 12)
_CEILING_BY_INTENSITY = (False, False, True, True)


def resolve_gibson_intensity(config: Optional[dict]) -> int:
    cfg = dict(config or {})
    try:
        value = int(cfg.get("intensity", DEFAULT_GIBSON_INTENSITY))
    except (TypeError, ValueError):
        return DEFAULT_GIBSON_INTENSITY
    return max(0, min(GIBSON_PANEL_ROWS, value))


def resolve_theme_name(config: Optional[dict]) -> str:
    cfg = dict(config or {})
    name = cfg.get("preset")
    if isinstance(name, str) and name in GIBSON_THEMES:
        return name
    return DEFAULT_THEME


def _clamp_rgb(value: Any) -> Optional[Color]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        return tuple(max(0, min(255, int(c))) for c in value)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def resolve_gibson_stops(config: Optional[dict]) -> Dict[str, Color]:
    cfg = dict(config or {})
    theme = dict(GIBSON_THEMES[resolve_theme_name(cfg)])
    aliases = {
        "grid": ("grid", "far"),
        "ice": ("ice", "mid"),
        "node": ("node", "near"),
    }
    for dest, keys in aliases.items():
        for key in keys:
            override = _clamp_rgb(cfg.get(key))
            if override is not None:
                theme[dest] = override
                break
    return theme


def resolve_speed(intensity: int) -> float:
    intensity = max(0, min(GIBSON_PANEL_ROWS, intensity))
    return float(_SPEED_BY_INTENSITY[intensity])


def resolve_output_gain(intensity: int) -> float:
    intensity = max(0, min(GIBSON_PANEL_ROWS, intensity))
    return float(_GAIN_BY_INTENSITY[intensity])


def resolve_x_lines(intensity: int) -> int:
    intensity = max(0, min(GIBSON_PANEL_ROWS, intensity))
    return int(_X_LINES_BY_INTENSITY[intensity])


def resolve_ice_count(intensity: int) -> int:
    intensity = max(0, min(GIBSON_PANEL_ROWS, intensity))
    return int(_ICE_COUNT_BY_INTENSITY[intensity])


def resolve_packet_count(intensity: int) -> int:
    intensity = max(0, min(GIBSON_PANEL_ROWS, intensity))
    return int(_PACKET_COUNT_BY_INTENSITY[intensity])


def resolve_draw_ceiling(intensity: int) -> bool:
    intensity = max(0, min(GIBSON_PANEL_ROWS, intensity))
    return bool(_CEILING_BY_INTENSITY[intensity])


def gibson_config_for_api(config: Optional[dict]) -> Dict[str, Any]:
    cfg = dict(config or {})
    intensity = resolve_gibson_intensity(cfg)
    stops = resolve_gibson_stops(cfg)
    preset = cfg.get("preset") if isinstance(cfg.get("preset"), str) else None
    if preset not in GIBSON_THEMES:
        preset = resolve_theme_name(cfg)
    return {
        "preset": preset,
        "intensity": intensity,
        "panel_rows": GIBSON_PANEL_ROWS,
        "speed": round(resolve_speed(intensity), 2),
        "output_gain": round(resolve_output_gain(intensity), 3),
        "ice_count": resolve_ice_count(intensity),
        "grid": list(stops["grid"]),
        "ice": list(stops["ice"]),
        "node": list(stops["node"]),
        "near": list(stops["node"]),
        "mid": list(stops["ice"]),
        "far": list(stops["grid"]),
        "presets": list(GIBSON_THEMES.keys()),
    }
