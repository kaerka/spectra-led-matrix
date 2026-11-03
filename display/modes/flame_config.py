"""Shared Galactic Unicorn fire config: flame vs lava profiles.

Settings are independent knobs on the shared effect panel (see
``effect_config.EFFECTS["flame"/"lava"]``): Brightness (output gain), Height
(share of the canvas the fire may reach), Activity (fuel, flicker and how
tall the tongues lick), colour cycle and intro. Older saved configs used a
single 0–3 ``intensity`` that tied height to brightness in panel rows;
``migrate_fire_config`` maps those onto the new keys when they are read.
See LICENSE.md for Pimoroni attribution.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Tuple

Color = Tuple[int, int, int]
FireProfile = Literal["flame", "lava"]

_GALACTIC_REF_HEIGHT = 11
_GALACTIC_REF_DAMPING = 0.97

DEFAULT_EMBER: Color = (20, 20, 20)
DEFAULT_BLACK: Color = (0, 0, 0)

FIRE_THEMES: Dict[str, Dict[str, Color]] = {
    "orange": {"core": (180, 30, 0), "mid": (220, 160, 0), "tip": (255, 255, 180)},
    "red": {"core": (200, 0, 0), "mid": (255, 50, 0), "tip": (255, 200, 120)},
    "yellow": {"core": (200, 120, 0), "mid": (255, 200, 0), "tip": (255, 255, 200)},
    "blue": {"core": (0, 40, 180), "mid": (40, 120, 255), "tip": (180, 220, 255)},
    "green": {"core": (0, 120, 40), "mid": (60, 200, 80), "tip": (180, 255, 200)},
    "purple": {"core": (80, 0, 160), "mid": (160, 40, 220), "tip": (220, 180, 255)},
    "cyan": {"core": (0, 140, 160), "mid": (0, 220, 255), "tip": (180, 255, 255)},
    "magenta": {"core": (160, 0, 120), "mid": (220, 0, 180), "tip": (255, 180, 240)},
    "white": {"core": (120, 120, 140), "mid": (200, 200, 220), "tip": (255, 255, 255)},
}
DEFAULT_THEME = "orange"

# Effect-panel palettes: (core, mid, tip, ember) per theme.
FIRE_PALETTES: Dict[str, Tuple[Color, ...]] = {
    name: (t["core"], t["mid"], t["tip"], DEFAULT_EMBER) for name, t in FIRE_THEMES.items()
}
FIRE_COLOR_LABELS = ("Core", "Middle", "Tips", "Embers")

HEIGHT_LABELS = ("Low", "Half", "High", "Full")
HEIGHT_FRACTIONS = (1 / 3, 1 / 2, 2 / 3, 1.0)
ACTIVITY_LABELS = ("Calm", "Normal", "Lively", "Wild")

# How the fire appears when the mode starts: rise from black (about 1–3 s),
# a slow build while the fuel eases in, or already burning.
INTRO_LABELS = ("Natural", "Slow build", "Instant")
SLOW_BUILD_S = 12.0

# Lava = archived dense heat look; flame = sparser tongues. Physics per Activity.
_PROFILES: Dict[str, Dict[str, Any]] = {
    "lava": {
        "damping": (0.990, 0.993, 0.996, 0.998),
        "seed_heat": (0.85, 1.0, 1.25, 1.5),
        "turbulence": (0.04, 0.05, 0.06, 0.08),
        "heat_scale": (220, 200, 185, 170),
        "seed_density": (1.0, 1.0, 1.0, 1.0),
        "sim_rate": (0.5, 0.7, 0.85, 1.0),
        "palette_bounds": (0.0, 0.06, 0.14, 0.30, 0.52, 1.0),
    },
    "flame": {
        # seed_density × seed_heat × heat_scale stays ≈ 84 so every level is
        # visibly lit up to its Height; Activity varies density and flicker.
        "damping": (0.985, 0.988, 0.992, 0.995),
        "seed_heat": (1.55, 1.55, 1.55, 1.55),
        "turbulence": (0.06, 0.09, 0.12, 0.15),
        "heat_scale": (181, 159, 146, 135),
        "seed_density": (0.30, 0.34, 0.37, 0.40),
        # Sim steps per frame (never above 1, so Wild costs what it always did).
        "sim_rate": (0.5, 0.7, 0.85, 1.0),
        "palette_bounds": (0.0, 0.10, 0.22, 0.40, 0.62, 1.0),
    },
}

# Old single-knob intensity → (brightness, height, activity). Night was 1.5 of
# 3 panel rows at 10 % gain; 1–3 were that many rows at full day gain.
_LEGACY_INTENSITY = {0: (0, 1, 0), 1: (3, 0, 1), 2: (3, 2, 2), 3: (3, 3, 3)}


def _profile(name: str) -> Dict[str, Any]:
    return _PROFILES.get(name, _PROFILES["flame"])


def _clamp_rgb(value: Any) -> Optional[Color]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        return tuple(max(0, min(255, int(c))) for c in value)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def migrate_fire_config(config: Optional[dict]) -> dict:
    """Fill the effect-panel keys from a pre-2026-11 flame/lava config.

    Keys already in the new format win, so a partly migrated config (new keys
    saved on top of old ones) resolves to what the user picked last.
    """
    cfg = dict(config or {})
    if "palette" not in cfg and "colors" not in cfg:
        legacy = {k: _clamp_rgb(cfg.get(k)) for k in ("core", "mid", "tip", "ember")}
        theme = cfg.get("preset") if cfg.get("preset") in FIRE_THEMES else None
        if any(legacy.values()):
            base = dict(FIRE_THEMES[theme or DEFAULT_THEME], ember=DEFAULT_EMBER)
            cfg["colors"] = [list(legacy[k] or base[k]) for k in ("core", "mid", "tip", "ember")]
        elif theme:
            cfg["palette"] = theme
    level = cfg.get("intensity")
    if isinstance(level, int) and not isinstance(level, bool) and level in _LEGACY_INTENSITY:
        for key, value in zip(("brightness", "height", "activity"), _LEGACY_INTENSITY[level]):
            cfg.setdefault(key, value)
    return cfg


def resolve_height_px(height: int, display_h: int) -> int:
    height = max(0, min(len(HEIGHT_FRACTIONS) - 1, height))
    return max(8, min(display_h, int(round(display_h * HEIGHT_FRACTIONS[height]))))


def resolve_fire_damping(profile: FireProfile, activity: int, height_px: int) -> float:
    """Heat kept per row; scaled so the tongues fade out near ``height_px``."""
    activity = max(0, min(3, activity))
    tier = float(_profile(profile)["damping"][activity])
    loss = (1.0 - _GALACTIC_REF_DAMPING) * (_GALACTIC_REF_HEIGHT / max(1, height_px))
    return min(0.9998, max(tier, 1.0 - loss))


def resolve_fire_physics(profile: FireProfile, activity: int) -> Dict[str, float]:
    activity = max(0, min(3, activity))
    p = _profile(profile)
    keys = ("seed_heat", "turbulence", "heat_scale", "seed_density", "sim_rate")
    return {key: float(p[key][activity]) for key in keys}


def fire_palette(stops: Tuple[Color, ...]) -> List[Color]:
    """Effect stops (core, mid, tip, ember) → LUT order black→ember→core→mid→tip."""
    core, mid, tip, ember = stops
    return [DEFAULT_BLACK, ember, core, mid, tip]


def build_fire_palette_lut(palette: List[Color], *, profile: FireProfile = "flame"):
    """256×3 RGB LUT with smooth interpolation across palette stops."""
    import numpy as np

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
