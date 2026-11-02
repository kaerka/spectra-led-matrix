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


def _tv_static_mode():
    from display.modes.tv_static import TvStaticMode

    return TvStaticMode()


def _snake_mode():
    from display.modes.snake import SnakeMode

    return SnakeMode()


def _wopr_mode():
    from display.modes.wopr import WoprMode

    return WoprMode()


def _gtw_mode():
    from display.modes.gtw import GtwMode

    return GtwMode()


def _tron_mode():
    from display.modes.tron import TronMode

    return TronMode()


def _falling_mode():
    from display.modes.falling import FallingMode

    return FallingMode()


def _plasma_mode():
    from display.modes.plasma import PlasmaMode

    return PlasmaMode()


def _fireworks_mode():
    from display.modes.fireworks import FireworksMode

    return FireworksMode()


def _boids_mode():
    from display.modes.boids import BoidsMode

    return BoidsMode()


def _sand_mode():
    from display.modes.sand import SandMode

    return SandMode()


def _automata_mode():
    from display.modes.automata import AutomataMode

    return AutomataMode()


def _dvd_mode():
    from display.modes.dvd import DvdMode

    return DvdMode()


def _wireframe_mode():
    from display.modes.wireframe import WireframeMode

    return WireframeMode()


def _mandelbrot_mode():
    from display.modes.mandelbrot import MandelbrotMode

    return MandelbrotMode()


def _pong_mode():
    from display.modes.pong import PongMode

    return PongMode()


def _tetris_mode():
    from display.modes.tetris import TetrisMode

    return TetrisMode()


def _breakout_mode():
    from display.modes.breakout import BreakoutMode

    return BreakoutMode()


def _invaders_mode():
    from display.modes.invaders import InvadersMode

    return InvadersMode()


def _pacman_mode():
    from display.modes.pacman import PacmanMode

    return PacmanMode()


def _gibson_mode():
    from display.modes.gibson import GibsonMode

    return GibsonMode()


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
        description="Three time zones (US East, Amsterdam, SPB) on the full panel.",
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
        label="Fire & smoke",
        description="Embers and drifting fire — per-display color themes; intensity 0–3.",
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
    "tv_static": ModeInfo(
        id="tv_static",
        label="TV static",
        description="No-signal CRT: noise, scanlines, roll bar, vignette.",
        factory=_tv_static_mode,
    ),
    "snake": ModeInfo(
        id="snake",
        label="Snake",
        description="Self-playing snake; restarts on win or death.",
        factory=_snake_mode,
    ),
    "wopr": ModeInfo(
        id="wopr",
        label="WOPR tic-tac-toe",
        description="Computer vs computer, perfect play — every game a draw. Faster and faster.",
        factory=_wopr_mode,
    ),
    "gtw": ModeInfo(
        id="gtw",
        label="WOPR: Global Conflict Simulation",
        description="Absurd random launches on a crude CRT world map. Winner: none possible.",
        factory=_gtw_mode,
    ),
    "tron": ModeInfo(
        id="tron",
        label="Tron light cycles",
        description="AI light cycles leave walls until they crash. Classic orange vs blue.",
        factory=_tron_mode,
    ),
    "falling": ModeInfo(
        id="falling",
        label="Falling",
        description="Stick figure tumbling while cave walls rush upward — infinite hole.",
        factory=_falling_mode,
    ),
    "plasma": ModeInfo(
        id="plasma",
        label="Plasma",
        description="Classic demoscene plasma — shifting colour fields.",
        factory=_plasma_mode,
    ),
    "fireworks": ModeInfo(
        id="fireworks",
        label="Fireworks",
        description="Launches, bursts, and fading particle trails.",
        factory=_fireworks_mode,
    ),
    "boids": ModeInfo(
        id="boids",
        label="Boids / fish tank",
        description="Flocking birds or an aquarium of fish with bubbles.",
        factory=_boids_mode,
    ),
    "sand": ModeInfo(
        id="sand",
        label="Falling sand / rain",
        description="Particle sand pile, or rain on glass with drips.",
        factory=_sand_mode,
    ),
    "automata": ModeInfo(
        id="automata",
        label="Cellular automata",
        description="Langton's ant, Brian's Brain, Wireworld, or reaction-diffusion.",
        factory=_automata_mode,
    ),
    "dvd": ModeInfo(
        id="dvd",
        label="Bouncing DVD logo",
        description="The classic logo bounce — celebrate every corner hit.",
        factory=_dvd_mode,
    ),
    "wireframe": ModeInfo(
        id="wireframe",
        label="Wireframe 3D",
        description="Spinning cube or torus — vector-display CRT look.",
        factory=_wireframe_mode,
    ),
    "mandelbrot": ModeInfo(
        id="mandelbrot",
        label="Mandelbrot zoom",
        description="Slow infinite zoom with palette cycling.",
        factory=_mandelbrot_mode,
    ),
    "pong": ModeInfo(
        id="pong",
        label="Pong",
        description="Self-playing Pong — two paddles, endless rally.",
        factory=_pong_mode,
    ),
    "tetris": ModeInfo(
        id="tetris",
        label="Tetris",
        description="Self-playing Tetris attract — drops, clears, resets when stacked.",
        factory=_tetris_mode,
    ),
    "breakout": ModeInfo(
        id="breakout",
        label="Breakout",
        description="Self-playing Breakout — paddle chases the ball, bricks fall.",
        factory=_breakout_mode,
    ),
    "invaders": ModeInfo(
        id="invaders",
        label="Space Invaders",
        description="Attract-mode invaders march and shoot; the bunker fights back.",
        factory=_invaders_mode,
    ),
    "pacman": ModeInfo(
        id="pacman",
        label="Pac-Man",
        description="Attract-mode Pac-Man chomps dots while ghosts patrol.",
        factory=_pacman_mode,
    ),
    "gibson": ModeInfo(
        id="gibson",
        label="Gibson (work in progress)",
        description="Neuromancer fly-through of textured towers. Placeholder textures, low frame rate.",
        factory=_gibson_mode,
    ),
}


def list_modes() -> List[ModeInfo]:
    return list(MODES.values())


def create_mode(mode_id: str):
    info = MODES.get(mode_id)
    if info is None:
        raise KeyError(f"Unknown display mode: {mode_id}")
    return info.factory()
