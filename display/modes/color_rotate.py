"""Shared slow hue-cycle for flame / lava / starfield.

``color_rotate_speed``: 0=off, 1=slow, 2=medium, 3=fast.
Phase lives in the mode (runtime); only speed is persisted in mode_config.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

Color = Tuple[int, int, int]

DEFAULT_COLOR_ROTATE_SPEED = 0
COLOR_ROTATE_MAX = 3
COLOR_ROTATE_LABELS = ("Off", "Slow", "Medium", "Fast")

# Full hue cycles per second at each speed tier (slow ≈ 2 min / lap).
_CYCLES_PER_SEC = (0.0, 1.0 / 120.0, 1.0 / 45.0, 1.0 / 18.0)


def resolve_color_rotate_speed(config: Optional[dict]) -> int:
    cfg = dict(config or {})
    try:
        value = int(cfg.get("color_rotate_speed", DEFAULT_COLOR_ROTATE_SPEED))
    except (TypeError, ValueError):
        return DEFAULT_COLOR_ROTATE_SPEED
    return max(0, min(COLOR_ROTATE_MAX, value))


def color_rotate_hz(speed: int) -> float:
    speed = max(0, min(COLOR_ROTATE_MAX, speed))
    return float(_CYCLES_PER_SEC[speed])


def color_rotate_api_fields(config: Optional[dict]) -> Dict[str, Any]:
    speed = resolve_color_rotate_speed(config)
    return {
        "color_rotate_speed": speed,
        "color_rotate_labels": list(COLOR_ROTATE_LABELS),
        "color_rotate_hz": round(color_rotate_hz(speed), 5),
    }


def _rgb_to_hsv(r: float, g: float, b: float) -> Tuple[float, float, float]:
    mx = max(r, g, b)
    mn = min(r, g, b)
    v = mx
    d = mx - mn
    s = 0.0 if mx <= 1e-9 else d / mx
    if d <= 1e-9:
        h = 0.0
    elif mx == r:
        h = ((g - b) / d) % 6.0
    elif mx == g:
        h = (b - r) / d + 2.0
    else:
        h = (r - g) / d + 4.0
    return (h / 6.0) % 1.0, s, v


def _hsv_to_rgb(h: float, s: float, v: float) -> Color:
    i = int(h * 6.0) % 6
    f = h * 6.0 - int(h * 6.0)
    p = v * (1.0 - s)
    q = v * (1.0 - f * s)
    t = v * (1.0 - (1.0 - f) * s)
    if i == 0:
        r, g, b = v, t, p
    elif i == 1:
        r, g, b = q, v, p
    elif i == 2:
        r, g, b = p, v, t
    elif i == 3:
        r, g, b = p, q, v
    elif i == 4:
        r, g, b = t, p, v
    else:
        r, g, b = v, p, q
    return (
        max(0, min(255, int(round(r * 255)))),
        max(0, min(255, int(round(g * 255)))),
        max(0, min(255, int(round(b * 255)))),
    )


def hue_shift_rgb(color: Sequence[int], offset: float) -> Color:
    """Shift hue by ``offset`` in [0, 1). Near-grays get saturation so whites cycle."""
    r, g, b = (max(0, min(255, int(c))) / 255.0 for c in color[:3])
    if r <= 1e-9 and g <= 1e-9 and b <= 1e-9:
        return (0, 0, 0)
    h, s, v = _rgb_to_hsv(r, g, b)
    if s < 0.08 and v > 0.04:
        s = 0.85
    return _hsv_to_rgb((h + offset) % 1.0, s, v)


def hue_shift_colors(colors: Sequence[Color], offset: float) -> List[Color]:
    if abs(offset) < 1e-9:
        return [tuple(c) for c in colors]  # type: ignore[misc]
    return [hue_shift_rgb(c, offset) for c in colors]
