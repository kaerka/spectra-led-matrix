"""Matrix rain config — shared by mode + web API."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

Color = Tuple[int, int, int]

RAIN_PRESETS: Dict[str, Color] = {
    "green": (0, 255, 70),
    "amber": (255, 150, 0),
    "red": (255, 30, 30),
    "cyan": (0, 220, 255),
    "blue": (40, 90, 255),
    "purple": (190, 60, 255),
    "pink": (255, 60, 170),
    "white": (220, 220, 220),
}
DEFAULT_PRESET = "green"

SPEED_LABELS = ("Calm", "Normal", "Fast", "Storm")
DEFAULT_SPEED = 1
MAX_SPEED = len(SPEED_LABELS) - 1

# Per speed level: drop speed range (cells / s) and share of columns raining.
_DROP_SPEED = ((4.0, 9.0), (7.0, 15.0), (11.0, 22.0), (16.0, 30.0))
_DENSITY = (0.35, 0.55, 0.75, 0.95)


def _clamp_rgb(value: Any) -> Optional[Color]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        return tuple(max(0, min(255, int(c))) for c in value)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def resolve_rain_color(config: Optional[dict]) -> Color:
    """Custom colour wins over a preset (setting a preset clears the custom colour)."""
    cfg = dict(config or {})
    custom = _clamp_rgb(cfg.get("color"))
    if custom is not None:
        return custom
    return RAIN_PRESETS.get(cfg.get("preset"), RAIN_PRESETS[DEFAULT_PRESET])


def resolve_rain_speed(config: Optional[dict]) -> int:
    try:
        value = int(dict(config or {}).get("speed", DEFAULT_SPEED))
    except (TypeError, ValueError):
        return DEFAULT_SPEED
    return max(0, min(MAX_SPEED, value))


def drop_speed_range(speed: int) -> Tuple[float, float]:
    return _DROP_SPEED[max(0, min(MAX_SPEED, speed))]


def rain_density(speed: int) -> float:
    return _DENSITY[max(0, min(MAX_SPEED, speed))]


def matrix_rain_config_for_api(config: Optional[dict]) -> Dict[str, Any]:
    cfg = dict(config or {})
    preset = cfg.get("preset") if cfg.get("preset") in RAIN_PRESETS else None
    if preset is None and _clamp_rgb(cfg.get("color")) is None:
        preset = DEFAULT_PRESET
    return {
        "preset": preset,
        "color": list(resolve_rain_color(cfg)),
        "presets": {name: list(rgb) for name, rgb in RAIN_PRESETS.items()},
        "speed": resolve_rain_speed(cfg),
        "speed_labels": list(SPEED_LABELS),
    }
