"""Display mode registry (lazy imports — parent web process must not load rgbmatrix)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List


@dataclass(frozen=True)
class ModeInfo:
    id: str
    label: str
    description: str
    factory: Callable[[], object]


def _weather_mode():
    from display.modes.weather import WeatherMode

    return WeatherMode()


def _world_clock_mode():
    from display.modes.world_clock import WorldClockMode

    return WorldClockMode()


def _game_of_life_mode():
    from display.modes.game_of_life import GameOfLifeMode

    return GameOfLifeMode()


def _media_mode():
    from display.modes.media import MediaMode

    return MediaMode()


def _flame_mode():
    from display.modes.flame import FlameMode

    return FlameMode()


def _lava_mode():
    from display.modes.lava import LavaMode

    return LavaMode()


def _starfield_mode():
    from display.modes.starfield import StarfieldMode

    return StarfieldMode()


def _analog_clock_mode():
    from display.modes.analog_clock import AnalogClockMode

    return AnalogClockMode()


def _matrix_rain_mode():
    from display.modes.matrix_rain import MatrixRainMode

    return MatrixRainMode()


def _rainbow_mode():
    from display.modes.rainbow import RainbowMode

    return RainbowMode()


def _sparkle_mode():
    from display.modes.sparkle import SparkleMode

    return SparkleMode()


def _lava_lamp_mode():
    from display.modes.lava_lamp import LavaLampMode

    return LavaLampMode()


MODES: Dict[str, ModeInfo] = {
    "weather": ModeInfo(
        id="weather",
        label="Weather + calendar",
        description="Local weather and time (plus a monthly calendar on the 192×192 walls).",
        factory=_weather_mode,
    ),
    "world_clock": ModeInfo(
        id="world_clock",
        label="World clock",
        description="Multiple time zones on the full panel (cities from clock.local.json).",
        factory=_world_clock_mode,
    ),
    "analog_clock": ModeInfo(
        id="analog_clock",
        label="Analog clock",
        description="Clock face with sweeping second hand (local time).",
        factory=_analog_clock_mode,
    ),
    "game_of_life": ModeInfo(
        id="game_of_life",
        label="Game of Life",
        description="Conway's Game of Life on the full panel.",
        factory=_game_of_life_mode,
    ),
    "media": ModeInfo(
        id="media",
        label="Animation / video",
        description="Full-screen GIF or MP4 from /data/spectra/media, scaled to the panel.",
        factory=_media_mode,
    ),
    "flame": ModeInfo(
        id="flame",
        label="Flame",
        description="Sparse procedural fire — per-display color themes; intensity 0–3.",
        factory=_flame_mode,
    ),
    "lava": ModeInfo(
        id="lava",
        label="Lava",
        description="Dense heat / lava field — softer on the PSU at ~70% gain.",
        factory=_lava_mode,
    ),
    "starfield": ModeInfo(
        id="starfield",
        label="Starfield",
        description="Fly through space (Win95-style); color modes + night intensity.",
        factory=_starfield_mode,
    ),
    "matrix_rain": ModeInfo(
        id="matrix_rain",
        label="Matrix rain",
        description="Falling glyph columns; pick any color and speed.",
        factory=_matrix_rain_mode,
    ),
    "rainbow": ModeInfo(
        id="rainbow",
        label="Rainbow",
        description="Colour bands flowing corner to corner; palettes or your own colours.",
        factory=_rainbow_mode,
    ),
    "sparkle": ModeInfo(
        id="sparkle",
        label="Sparkle",
        description="Blinkenlights — pixels or lamps twinkling and blinking at their own pace.",
        factory=_sparkle_mode,
    ),
    "lava_lamp": ModeInfo(
        id="lava_lamp",
        label="Lava lamp",
        description="Wax blobs rising and sinking; pick speed, wax and liquid colours.",
        factory=_lava_lamp_mode,
    ),
}


def list_modes() -> List[ModeInfo]:
    return list(MODES.values())


def create_mode(mode_id: str):
    info = MODES.get(mode_id)
    if info is None:
        raise KeyError(f"Unknown display mode: {mode_id}")
    return info.factory()
