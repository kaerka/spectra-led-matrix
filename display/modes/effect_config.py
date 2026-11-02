"""Shared settings for procedural effects (rainbow, sparkle, lava lamp).

Each effect declares its palettes, custom colour slots and option button rows;
the web UIs build their controls from ``effect_config_for_api`` so a new effect
needs no new panel code. Stored in ``mode_config[mode_id]`` as
``{"palette": name}`` or ``{"colors": [[r, g, b], ...]}`` plus one int per option.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple

Color = Tuple[int, int, int]

BRIGHTNESS_LABELS = ("Night", "Low", "Medium", "High")

SPECTRUM: Tuple[Color, ...] = (
    (255, 0, 0), (255, 255, 0), (0, 255, 0), (0, 255, 255), (0, 0, 255), (255, 0, 255),
)


@dataclass(frozen=True)
class EffectOption:
    key: str
    label: str
    choices: Tuple[str, ...]
    default: int


@dataclass(frozen=True)
class EffectSpec:
    mode_id: str
    title: str
    hint: str
    palettes: Dict[str, Tuple[Color, ...]]
    default_palette: str
    color_labels: Tuple[str, ...]
    options: Tuple[EffectOption, ...]
    # Pixel RGB multiplier per brightness level; full-screen effects stay below
    # 1.0 at "High" to keep the walls' PSUs comfortable (same idea as lava).
    gains: Tuple[float, ...]
    # Palettes sampled as a continuous gradient rather than as discrete colours.
    continuous: FrozenSet[str] = field(default_factory=frozenset)


def _brightness(default: int = 3) -> EffectOption:
    return EffectOption("brightness", "Brightness", BRIGHTNESS_LABELS, default)


EFFECTS: Dict[str, EffectSpec] = {
    "rainbow": EffectSpec(
        mode_id="rainbow",
        title="Rainbow",
        hint="Colour bands flowing from one corner to the other.",
        palettes={
            "spectrum": SPECTRUM,
            "pastel": ((255, 140, 140), (255, 220, 140), (150, 255, 160),
                       (140, 220, 255), (170, 150, 255), (255, 150, 230)),
            "sunset": ((255, 40, 0), (255, 140, 0), (255, 60, 120), (120, 0, 160)),
            "ocean": ((0, 40, 255), (0, 200, 255), (0, 255, 170), (0, 90, 160)),
            "forest": ((0, 255, 40), (150, 255, 0), (0, 120, 40), (0, 200, 120)),
            "fire": ((255, 0, 0), (255, 120, 0), (255, 220, 0), (255, 60, 0)),
            "neon": ((255, 0, 180), (0, 255, 255), (180, 0, 255), (0, 255, 100)),
            "ice": ((255, 255, 255), (120, 200, 255), (0, 80, 255), (160, 240, 255)),
        },
        default_palette="spectrum",
        color_labels=("Color 1", "Color 2", "Color 3", "Color 4"),
        options=(
            EffectOption("speed", "Speed", ("Slow", "Normal", "Fast", "Warp"), 1),
            EffectOption("direction", "From corner",
                         ("Top-left ↘", "Top-right ↙", "Bottom-right ↖", "Bottom-left ↗"), 0),
            EffectOption("bands", "Bands", ("Wide", "Medium", "Narrow"), 0),
            _brightness(),
        ),
        gains=(0.08, 0.25, 0.45, 0.70),
    ),
    "sparkle": EffectSpec(
        mode_id="sparkle",
        title="Sparkle",
        hint="Blinkenlights: every light twinkles or blinks at its own pace.",
        palettes={
            "rainbow": SPECTRUM,
            "retro": ((255, 30, 0), (255, 150, 0), (40, 255, 40), (255, 240, 200)),
            "christmas": ((255, 20, 20), (20, 255, 40), (255, 180, 40), (255, 255, 255)),
            "ice": ((255, 255, 255), (140, 220, 255), (40, 120, 255), (200, 240, 255)),
            "fire": ((255, 30, 0), (255, 110, 0), (255, 200, 30), (255, 255, 180)),
            "candy": ((255, 80, 180), (120, 220, 255), (255, 240, 120), (180, 120, 255)),
            "starlight": ((255, 255, 255), (255, 230, 190), (220, 235, 255), (255, 255, 255)),
        },
        default_palette="rainbow",
        color_labels=("Color 1", "Color 2", "Color 3", "Color 4"),
        options=(
            EffectOption("style", "Style", ("Twinkle", "Blink"), 0),
            EffectOption("density", "Density", ("Sparse", "Some", "Many", "Lots"), 1),
            EffectOption("speed", "Speed", ("Slow", "Normal", "Fast", "Frantic"), 1),
            EffectOption("size", "Lights", ("Pixels", "Lamps", "Big lamps"), 0),
            _brightness(),
        ),
        gains=(0.15, 0.40, 0.70, 1.0),
        continuous=frozenset({"rainbow"}),
    ),
    "lava_lamp": EffectSpec(
        mode_id="lava_lamp",
        title="Lava lamp",
        hint="Wax blobs rising and sinking; pick wax and liquid colours.",
        palettes={
            "classic": ((255, 90, 0), (110, 0, 20)),
            "retro": ((255, 40, 150), (10, 20, 120)),
            "lime": ((170, 255, 0), (0, 70, 60)),
            "ocean": ((0, 230, 255), (40, 0, 110)),
            "sunset": ((255, 200, 0), (150, 0, 70)),
            "ghost": ((230, 230, 255), (40, 0, 80)),
            "ruby": ((255, 20, 40), (40, 0, 10)),
        },
        default_palette="classic",
        color_labels=("Wax", "Liquid"),
        options=(
            EffectOption("speed", "Speed", ("Calm", "Normal", "Lively", "Fast"), 1),
            EffectOption("blobs", "Blobs", ("Few", "Some", "Many"), 1),
            _brightness(),
        ),
        gains=(0.10, 0.30, 0.55, 0.85),
    ),
    "tv_static": EffectSpec(
        mode_id="tv_static",
        title="TV static",
        hint="No-signal CRT: noise, scanlines, roll bar, vignette.",
        palettes={
            "mono": ((220, 220, 220),),
            "green": ((40, 255, 80),),
            "amber": ((255, 180, 40),),
            "blue": ((80, 140, 255),),
            "pink": ((255, 80, 180),),
        },
        default_palette="mono",
        color_labels=("Tint",),
        options=(
            EffectOption("intensity", "Noise", ("Soft", "Normal", "Harsh"), 1),
            EffectOption("roll", "Roll bar", ("Off", "Rare", "Often"), 1),
            _brightness(2),
        ),
        gains=(0.12, 0.35, 0.55, 0.75),
    ),
    "snake": EffectSpec(
        mode_id="snake",
        title="Snake",
        hint="Self-playing snake; restarts on win or death.",
        palettes={
            "classic": ((40, 220, 40), (255, 60, 60)),
            "neon": ((0, 255, 180), (255, 0, 220)),
            "amber": ((255, 180, 40), (255, 80, 40)),
            "ice": ((140, 220, 255), (255, 255, 255)),
            "candy": ((255, 80, 180), (120, 220, 255)),
        },
        default_palette="classic",
        color_labels=("Snake", "Food"),
        options=(
            EffectOption("speed", "Speed", ("Slow", "Normal", "Fast", "Crazy"), 1),
            EffectOption("grid", "Grid", ("Fine", "Medium", "Coarse"), 1),
            _brightness(),
        ),
        gains=(0.20, 0.45, 0.70, 1.0),
    ),
    "wopr": EffectSpec(
        mode_id="wopr",
        title="WOPR tic-tac-toe",
        hint="Computer vs computer, perfect play — every game a draw. Faster and faster.",
        palettes={
            "amber": ((255, 160, 40), (255, 200, 80)),
            "green": ((40, 255, 80), (120, 255, 140)),
            "cyan": ((40, 220, 255), (140, 240, 255)),
            "red": ((255, 60, 40), (255, 140, 100)),
        },
        default_palette="amber",
        color_labels=("Grid", "Marks"),
        options=(
            EffectOption("speed", "Pace", ("Think", "Normal", "Rapid", "Blitz"), 1),
            EffectOption("card", "Strange game", ("Rare", "Sometimes", "Often"), 1),
            _brightness(),
        ),
        gains=(0.25, 0.50, 0.75, 1.0),
    ),
    "gtw": EffectSpec(
        mode_id="gtw",
        title="WOPR: Global Conflict Simulation",
        hint="Absurd random launches on a crude CRT world map. Winner: none possible.",
        palettes={
            "amber": ((255, 160, 40), (255, 220, 100)),
            "green": ((40, 255, 80), (180, 255, 180)),
            "cyan": ((40, 220, 255), (180, 240, 255)),
            "phosphor": ((120, 255, 140), (255, 200, 80)),
        },
        default_palette="amber",
        color_labels=("Map", "Missiles"),
        options=(
            EffectOption("speed", "Pace", ("Think", "Normal", "Rapid", "Blitz"), 1),
            EffectOption("parable", "Parables", ("Rare", "Sometimes", "Often"), 1),
            _brightness(),
        ),
        gains=(0.25, 0.50, 0.75, 1.0),
    ),
    "tron": EffectSpec(
        mode_id="tron",
        title="Tron light cycles",
        hint="AI light cycles leave walls until they crash. Classic orange vs blue.",
        palettes={
            # Defaults: Bike 1 orange, Bike 2 blue; extras for 3–5 players.
            "classic": (
                (255, 140, 20), (40, 160, 255), (0, 255, 220), (255, 60, 200), (180, 255, 40),
            ),
            "neon": (
                (255, 0, 200), (0, 255, 255), (255, 255, 0), (120, 0, 255), (0, 255, 100),
            ),
            "ice": (
                (220, 240, 255), (80, 160, 255), (160, 220, 255), (255, 255, 255), (100, 200, 255),
            ),
            "sunset": (
                (255, 80, 20), (255, 180, 40), (255, 60, 120), (180, 40, 255), (255, 220, 100),
            ),
        },
        default_palette="classic",
        color_labels=("Bike 1", "Bike 2", "Bike 3", "Bike 4", "Bike 5"),
        options=(
            EffectOption("bikes", "Bikes", ("2", "3", "4", "5"), 0),
            EffectOption("speed", "Speed", ("Slow", "Normal", "Fast", "Warp"), 1),
            _brightness(),
        ),
        gains=(0.20, 0.45, 0.70, 1.0),
    ),
    "falling": EffectSpec(
        mode_id="falling",
        title="Falling",
        hint="Stick figure tumbling while cave walls rush upward — infinite hole.",
        palettes={
            "amber": ((255, 180, 60), (80, 50, 20)),
            "ice": ((200, 230, 255), (40, 60, 90)),
            "toxic": ((120, 255, 40), (20, 40, 10)),
            "neon": ((255, 80, 200), (40, 0, 60)),
        },
        default_palette="amber",
        color_labels=("Figure", "Walls"),
        options=(
            EffectOption("speed", "Speed", ("Slow", "Normal", "Fast", "Freefall"), 1),
            _brightness(),
        ),
        gains=(0.20, 0.45, 0.70, 1.0),
    ),
    "plasma": EffectSpec(
        mode_id="plasma",
        title="Plasma",
        hint="Classic demoscene plasma — shifting colour fields.",
        palettes={
            "spectrum": SPECTRUM,
            "neon": ((255, 0, 180), (0, 255, 255), (180, 0, 255), (0, 255, 100)),
            "fire": ((255, 0, 0), (255, 120, 0), (255, 220, 0), (255, 60, 0)),
            "ocean": ((0, 40, 255), (0, 200, 255), (0, 255, 170), (0, 90, 160)),
            "ice": ((255, 255, 255), (120, 200, 255), (0, 80, 255), (160, 240, 255)),
        },
        default_palette="spectrum",
        color_labels=("Color 1", "Color 2", "Color 3", "Color 4"),
        options=(
            EffectOption("speed", "Speed", ("Slow", "Normal", "Fast", "Warp"), 1),
            EffectOption("scale", "Scale", ("Wide", "Medium", "Tight"), 1),
            _brightness(2),
        ),
        gains=(0.10, 0.30, 0.50, 0.70),
        continuous=frozenset({"spectrum", "neon", "fire", "ocean", "ice"}),
    ),
    "fireworks": EffectSpec(
        mode_id="fireworks",
        title="Fireworks",
        hint="Launches, bursts, and fading particle trails.",
        palettes={
            "festive": ((255, 60, 60), (255, 200, 40), (80, 255, 120), (80, 160, 255), (255, 80, 220)),
            "gold": ((255, 220, 80), (255, 160, 40), (255, 255, 200)),
            "neon": ((255, 0, 200), (0, 255, 255), (180, 255, 0), (255, 80, 40)),
            "ice": ((220, 240, 255), (120, 180, 255), (255, 255, 255)),
        },
        default_palette="festive",
        color_labels=("Color 1", "Color 2", "Color 3", "Color 4"),
        options=(
            EffectOption("rate", "Launches", ("Sparse", "Some", "Many", "Barrage"), 1),
            EffectOption("speed", "Speed", ("Slow", "Normal", "Fast", "Frantic"), 1),
            _brightness(),
        ),
        gains=(0.20, 0.45, 0.70, 1.0),
    ),
    "boids": EffectSpec(
        mode_id="boids",
        title="Boids / fish tank",
        hint="Flocking birds or an aquarium of fish with bubbles.",
        palettes={
            "sky": ((200, 220, 255), (40, 80, 140), (255, 255, 255)),
            "reef": ((255, 120, 60), (40, 200, 255), (80, 40, 160)),
            "neon": ((0, 255, 200), (255, 0, 180), (255, 255, 80)),
            "mono": ((220, 220, 220), (80, 80, 80), (255, 255, 255)),
        },
        default_palette="reef",
        color_labels=("Creatures", "Water", "Accent"),
        options=(
            EffectOption("style", "Style", ("Flock", "Fish tank"), 1),
            EffectOption("count", "Count", ("Few", "Some", "Many"), 1),
            EffectOption("speed", "Speed", ("Lazy", "Normal", "Busy", "Frantic"), 1),
            _brightness(),
        ),
        gains=(0.15, 0.40, 0.65, 0.90),
    ),
    "sand": EffectSpec(
        mode_id="sand",
        title="Falling sand / rain",
        hint="Particle sand pile, or rain on glass with drips.",
        palettes={
            "sand": ((220, 180, 80), (40, 30, 20)),
            "ember": ((255, 120, 40), (40, 10, 0)),
            "rain": ((140, 180, 255), (10, 20, 40)),
            "acid": ((120, 255, 40), (10, 30, 10)),
        },
        default_palette="sand",
        color_labels=("Particles", "Background"),
        options=(
            EffectOption("style", "Style", ("Sand", "Rain"), 0),
            EffectOption("rate", "Rate", ("Drizzle", "Normal", "Heavy", "Storm"), 1),
            _brightness(),
        ),
        gains=(0.15, 0.40, 0.65, 0.90),
    ),
    "automata": EffectSpec(
        mode_id="automata",
        title="Cellular automata",
        hint="Langton's ant, Brian's Brain, Wireworld, or reaction-diffusion.",
        palettes={
            "classic": ((255, 255, 255), (8, 8, 12), (255, 80, 40), (40, 160, 255)),
            "neon": ((0, 255, 180), (20, 20, 40), (255, 0, 200), (255, 220, 40)),
            "amber": ((255, 180, 40), (20, 12, 0), (255, 80, 20), (255, 220, 120)),
            "ice": ((200, 230, 255), (10, 20, 40), (80, 160, 255), (255, 255, 255)),
        },
        default_palette="classic",
        color_labels=("Alive", "Dead", "Accent", "Spark"),
        options=(
            EffectOption("kind", "Kind", ("Langton", "Brian", "Wireworld", "RD"), 0),
            EffectOption("speed", "Speed", ("Slow", "Normal", "Fast", "Warp"), 1),
            _brightness(),
        ),
        gains=(0.15, 0.40, 0.65, 0.90),
    ),
    "dvd": EffectSpec(
        mode_id="dvd",
        title="Bouncing DVD logo",
        hint="The classic logo bounce — celebrate every corner hit.",
        palettes={
            "classic": ((255, 80, 40),),
            "neon": ((0, 255, 180),),
            "gold": ((255, 200, 40),),
            "ice": ((160, 220, 255),),
            "pink": ((255, 80, 180),),
        },
        default_palette="classic",
        color_labels=("Logo",),
        options=(
            EffectOption("speed", "Speed", ("Slow", "Normal", "Fast", "Warp"), 1),
            EffectOption("size", "Size", ("Small", "Medium", "Large"), 1),
            _brightness(),
        ),
        gains=(0.25, 0.50, 0.75, 1.0),
    ),
    "wireframe": EffectSpec(
        mode_id="wireframe",
        title="Wireframe 3D",
        hint="Spinning cube or torus — vector-display CRT look.",
        palettes={
            "amber": ((255, 180, 40),),
            "green": ((40, 255, 80),),
            "cyan": ((40, 220, 255),),
            "white": ((220, 220, 220),),
        },
        default_palette="amber",
        color_labels=("Lines",),
        options=(
            EffectOption("shape", "Shape", ("Cube", "Torus"), 0),
            EffectOption("speed", "Spin", ("Slow", "Normal", "Fast", "Warp"), 1),
            _brightness(),
        ),
        gains=(0.25, 0.50, 0.75, 1.0),
    ),
    "mandelbrot": EffectSpec(
        mode_id="mandelbrot",
        title="Mandelbrot zoom",
        hint="Slow infinite zoom with palette cycling.",
        palettes={
            "spectrum": SPECTRUM,
            "fire": ((0, 0, 0), (255, 40, 0), (255, 180, 0), (255, 255, 200)),
            "ocean": ((0, 0, 40), (0, 80, 255), (0, 220, 255), (200, 255, 255)),
            "neon": ((0, 0, 0), (255, 0, 180), (0, 255, 255), (255, 255, 80)),
        },
        default_palette="spectrum",
        color_labels=("Color 1", "Color 2", "Color 3", "Color 4"),
        options=(
            EffectOption("speed", "Zoom", ("Crawl", "Slow", "Normal", "Fast"), 1),
            EffectOption("detail", "Detail", ("Coarse", "Normal", "Fine"), 1),
            _brightness(2),
        ),
        gains=(0.12, 0.35, 0.55, 0.75),
        continuous=frozenset({"spectrum", "fire", "ocean", "neon"}),
    ),
    "pong": EffectSpec(
        mode_id="pong",
        title="Pong",
        hint="Self-playing Pong — two paddles, endless rally.",
        palettes={
            "classic": ((220, 220, 220), (220, 220, 220)),
            "amber": ((255, 180, 40), (255, 200, 80)),
            "neon": ((0, 255, 180), (255, 0, 200)),
            "ice": ((160, 220, 255), (255, 255, 255)),
        },
        default_palette="classic",
        color_labels=("Left", "Right"),
        options=(
            EffectOption("speed", "Speed", ("Slow", "Normal", "Fast", "Warp"), 1),
            _brightness(),
        ),
        gains=(0.25, 0.50, 0.75, 1.0),
    ),
    "tetris": EffectSpec(
        mode_id="tetris",
        title="Tetris",
        hint="Self-playing Tetris attract — drops, clears, resets when stacked.",
        palettes={
            "classic": (
                (0, 240, 240), (0, 0, 240), (240, 160, 0), (240, 240, 0),
                (0, 240, 0), (160, 0, 240), (240, 0, 0),
            ),
            "neon": (
                (0, 255, 255), (80, 80, 255), (255, 160, 0), (255, 255, 0),
                (0, 255, 100), (200, 0, 255), (255, 40, 80),
            ),
            "mono": ((220, 220, 220), (180, 180, 180), (140, 140, 140), (255, 255, 255)),
        },
        default_palette="classic",
        color_labels=("I", "J", "L", "O", "S", "T", "Z"),
        options=(
            EffectOption("speed", "Speed", ("Slow", "Normal", "Fast", "Warp"), 1),
            _brightness(),
        ),
        gains=(0.20, 0.45, 0.70, 1.0),
    ),
    "breakout": EffectSpec(
        mode_id="breakout",
        title="Breakout",
        hint="Self-playing Breakout — paddle chases the ball, bricks fall.",
        palettes={
            "classic": ((220, 220, 220), (255, 60, 60), (255, 180, 40), (40, 200, 80), (40, 120, 255)),
            "neon": ((255, 255, 255), (255, 0, 180), (0, 255, 255), (180, 255, 0), (120, 0, 255)),
            "amber": ((255, 200, 80), (255, 140, 40), (255, 80, 20), (200, 60, 0), (255, 220, 120)),
        },
        default_palette="classic",
        color_labels=("Ball", "Brick 1", "Brick 2", "Brick 3", "Brick 4"),
        options=(
            EffectOption("speed", "Speed", ("Slow", "Normal", "Fast", "Warp"), 1),
            _brightness(),
        ),
        gains=(0.20, 0.45, 0.70, 1.0),
    ),
    "invaders": EffectSpec(
        mode_id="invaders",
        title="Space Invaders",
        hint="Attract-mode invaders march and shoot; the bunker fights back.",
        palettes={
            "classic": ((40, 255, 80), (255, 255, 255), (255, 60, 60)),
            "amber": ((255, 180, 40), (255, 220, 120), (255, 80, 20)),
            "neon": ((0, 255, 200), (255, 255, 255), (255, 0, 180)),
        },
        default_palette="classic",
        color_labels=("Aliens", "Ship", "Shots"),
        options=(
            EffectOption("speed", "Speed", ("Slow", "Normal", "Fast", "Warp"), 1),
            _brightness(),
        ),
        gains=(0.20, 0.45, 0.70, 1.0),
    ),
    "pacman": EffectSpec(
        mode_id="pacman",
        title="Pac-Man",
        hint="Attract-mode Pac-Man chomps dots while ghosts patrol.",
        palettes={
            "classic": ((255, 220, 0), (255, 40, 40), (255, 140, 200), (40, 220, 255), (255, 140, 40)),
            "neon": ((255, 255, 80), (255, 0, 120), (0, 255, 200), (120, 80, 255), (255, 160, 0)),
            "mono": ((220, 220, 220), (180, 180, 180), (140, 140, 140), (255, 255, 255), (100, 100, 100)),
        },
        default_palette="classic",
        color_labels=("Pac-Man", "Blinky", "Pinky", "Inky", "Clyde"),
        options=(
            EffectOption("speed", "Speed", ("Slow", "Normal", "Fast", "Warp"), 1),
            _brightness(),
        ),
        gains=(0.20, 0.45, 0.70, 1.0),
    ),
}

EFFECT_MODE_IDS: Tuple[str, ...] = tuple(EFFECTS)


@dataclass(frozen=True)
class EffectSettings:
    palette: Optional[str]
    stops: Tuple[Color, ...]
    values: Dict[str, int]
    gain: float
    continuous: bool


def _rgb(value: Any) -> Optional[Color]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        rgb = tuple(int(c) for c in value)
    except (TypeError, ValueError):
        return None
    if any(c < 0 or c > 255 for c in rgb):
        return None
    return rgb  # type: ignore[return-value]


def _custom_colors(spec: EffectSpec, value: Any) -> Optional[Tuple[Color, ...]]:
    if not isinstance(value, (list, tuple)) or len(value) != len(spec.color_labels):
        return None
    colors = tuple(_rgb(c) for c in value)
    return None if any(c is None for c in colors) else colors  # type: ignore[return-value]


def _option_value(opt: EffectOption, value: Any) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return opt.default
    return v if 0 <= v < len(opt.choices) else opt.default


def sample_cyclic(stops: Sequence[Color], count: int) -> Tuple[Color, ...]:
    """``count`` colours evenly spaced around the looped gradient through ``stops``."""
    if len(stops) == count:
        return tuple(stops)
    out = []
    for i in range(count):
        pos = i * len(stops) / count
        a, frac = int(pos), pos - int(pos)
        c0, c1 = stops[a % len(stops)], stops[(a + 1) % len(stops)]
        out.append(tuple(int(round(c0[k] + (c1[k] - c0[k]) * frac)) for k in range(3)))
    return tuple(out)  # type: ignore[return-value]


def resolve_effect(mode_id: str, config: Optional[dict]) -> EffectSettings:
    spec = EFFECTS[mode_id]
    cfg = dict(config or {})
    custom = _custom_colors(spec, cfg.get("colors"))
    if custom is not None:
        palette, stops = None, custom
    else:
        palette = cfg.get("palette") if cfg.get("palette") in spec.palettes else spec.default_palette
        stops = spec.palettes[palette]
    values = {opt.key: _option_value(opt, cfg.get(opt.key, opt.default)) for opt in spec.options}
    level = values.get("brightness", len(spec.gains) - 1)
    return EffectSettings(
        palette=palette,
        stops=stops,
        values=values,
        gain=spec.gains[min(level, len(spec.gains) - 1)],
        continuous=palette in spec.continuous,
    )


def validate_effect_patch(mode_id: str, patch: Any) -> Dict[str, Any]:
    """Clean a PUT body; raises ValueError with a user-facing message."""
    spec = EFFECTS[mode_id]
    if not isinstance(patch, dict) or not patch:
        raise ValueError("Provide palette, colors, and/or an option")
    clean: Dict[str, Any] = {}
    options = {opt.key: opt for opt in spec.options}
    for key, value in patch.items():
        if key == "palette":
            if value not in spec.palettes:
                raise ValueError(f"Unknown palette {value!r}")
            clean["palette"] = value
        elif key == "colors":
            colors = _custom_colors(spec, value)
            if colors is None:
                raise ValueError(f"colors must be {len(spec.color_labels)} [r, g, b] values 0-255")
            clean["colors"] = [list(c) for c in colors]
        elif key in options:
            opt = options[key]
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < len(opt.choices):
                raise ValueError(f"{key} must be 0-{len(opt.choices) - 1}")
            clean[key] = value
        else:
            raise ValueError(f"Unknown setting {key!r}")
    if "palette" in clean and "colors" in clean:
        raise ValueError("Send palette or colors, not both")
    return clean


def effect_config_for_api(mode_id: str, config: Optional[dict]) -> Dict[str, Any]:
    spec = EFFECTS[mode_id]
    settings = resolve_effect(mode_id, config)
    return {
        "mode_id": mode_id,
        "title": spec.title,
        "hint": spec.hint,
        "palette": settings.palette,
        "colors": [list(c) for c in sample_cyclic(settings.stops, len(spec.color_labels))],
        "palettes": {name: [list(c) for c in stops] for name, stops in spec.palettes.items()},
        "color_labels": list(spec.color_labels),
        "options": [
            {"key": opt.key, "label": opt.label, "choices": list(opt.choices), "value": settings.values[opt.key]}
            for opt in spec.options
        ],
    }
