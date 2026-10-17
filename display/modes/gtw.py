"""WOPR: Global Conflict Simulation — absurd random launches on a crude CRT map."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw

from display.bitmap_fonts import draw_ink_centered, load_bdf, text_size
from display.modes.effect_base import EffectField, EffectMode

# Pace = seconds between launches (kept shorter than flight so many arcs overlap).
_BASE_PACE = (1.15, 0.85, 0.65, 0.48)
_PARABLE_CHANCE = (0.10, 0.28, 0.50)
_END_HOLD = 4.5
# Teletype / parable lines stay long enough to read.
_TEXT_HOLD = 5.0
_PARABLE_HOLD = 5.0
# Flight time to target (Think…Blitz) — slow CRT tracks, several in the air.
_ARC_DUR = (5.0, 4.2, 3.6, 3.0)
# Long rounds even on Blitz (~0.5s cadence × 60 ≈ 30s of launches + flights).
_MAX_LAUNCHES = 60

# Distinct marker hues — assigned by site index, not geography (no alliances).
_SITE_HUES = (
    (255, 60, 60), (60, 120, 255), (255, 160, 40), (40, 255, 180),
    (255, 80, 220), (180, 255, 40), (80, 220, 255), (255, 220, 60),
    (200, 80, 255), (40, 255, 100), (255, 100, 140), (120, 180, 255),
)

# Recognisable-but-crude continent outlines (unit coords, x west→east, y north→south).
_CONTINENTS: tuple[tuple[tuple[float, float], ...], ...] = (
    # North America — Alaska jut, Hudson Bay, Florida, Baja, Mexico taper
    (
        (0.02, 0.22), (0.06, 0.14), (0.12, 0.12), (0.16, 0.16),  # Alaska
        (0.20, 0.12), (0.28, 0.10), (0.34, 0.14), (0.32, 0.20),  # Arctic / Hudson
        (0.30, 0.26), (0.34, 0.30), (0.32, 0.36), (0.28, 0.38),  # NE / Great Lakes
        (0.30, 0.44), (0.28, 0.48), (0.26, 0.46),  # Florida
        (0.20, 0.44), (0.16, 0.48), (0.14, 0.54), (0.12, 0.50),  # Mexico / Baja
        (0.10, 0.42), (0.08, 0.34), (0.06, 0.28), (0.02, 0.22),
    ),
    # South America — Brazil bulge east, Andes west, tip south
    (
        (0.26, 0.52), (0.30, 0.50), (0.36, 0.52), (0.40, 0.58), (0.38, 0.66),
        (0.34, 0.74), (0.32, 0.82), (0.30, 0.86), (0.28, 0.82), (0.26, 0.74),
        (0.24, 0.66), (0.22, 0.58), (0.24, 0.54), (0.26, 0.52),
    ),
    # Greenland
    (
        (0.36, 0.06), (0.40, 0.04), (0.44, 0.06), (0.46, 0.12), (0.44, 0.18),
        (0.40, 0.20), (0.36, 0.16), (0.34, 0.10), (0.36, 0.06),
    ),
    # UK + Ireland (tiny)
    ((0.46, 0.20), (0.48, 0.18), (0.50, 0.20), (0.49, 0.24), (0.47, 0.24), (0.46, 0.20)),
    ((0.44, 0.22), (0.45, 0.21), (0.46, 0.23), (0.45, 0.24), (0.44, 0.22)),
    # Europe — Scandinavia, Iberia, Italy boot, Balkans
    (
        (0.50, 0.10), (0.54, 0.08), (0.56, 0.12), (0.54, 0.18),  # Scandinavia
        (0.58, 0.20), (0.60, 0.24), (0.58, 0.28), (0.56, 0.32),  # E Europe / Balkans
        (0.54, 0.34), (0.55, 0.38), (0.53, 0.36),  # Italy
        (0.50, 0.34), (0.48, 0.32), (0.46, 0.30), (0.46, 0.26),  # Iberia / France
        (0.48, 0.22), (0.50, 0.18), (0.50, 0.10),
    ),
    # Africa — Horn, Gulf of Guinea, southern taper
    (
        (0.50, 0.36), (0.56, 0.34), (0.60, 0.36), (0.64, 0.40), (0.66, 0.44),  # Horn
        (0.62, 0.48), (0.60, 0.56), (0.58, 0.64), (0.56, 0.72), (0.54, 0.76),
        (0.50, 0.72), (0.48, 0.64), (0.46, 0.54), (0.44, 0.46), (0.46, 0.40),
        (0.48, 0.36), (0.50, 0.36),
    ),
    # Madagascar
    ((0.64, 0.62), (0.66, 0.60), (0.67, 0.68), (0.65, 0.72), (0.64, 0.66), (0.64, 0.62)),
    # Asia — Urals→Siberia→Kamchatka, India, SE Asia, Korea
    (
        (0.58, 0.14), (0.66, 0.10), (0.76, 0.08), (0.86, 0.10), (0.94, 0.14),  # Arctic Siberia
        (0.96, 0.20), (0.94, 0.26), (0.90, 0.24),  # Kamchatka
        (0.88, 0.30), (0.86, 0.34), (0.84, 0.32),  # Korea / Japan shelf
        (0.82, 0.38), (0.80, 0.44), (0.78, 0.50), (0.76, 0.54), (0.74, 0.50),  # SE Asia
        (0.72, 0.46), (0.70, 0.50), (0.68, 0.54), (0.66, 0.50), (0.68, 0.44),  # India
        (0.66, 0.38), (0.62, 0.34), (0.60, 0.28), (0.58, 0.22), (0.58, 0.14),
    ),
    # Japan
    ((0.88, 0.30), (0.90, 0.28), (0.92, 0.32), (0.90, 0.38), (0.88, 0.36), (0.88, 0.30)),
    # Indonesia chain (schematic)
    ((0.78, 0.54), (0.84, 0.52), (0.90, 0.54), (0.88, 0.58), (0.82, 0.58), (0.78, 0.56), (0.78, 0.54)),
    # Australia + Tasmania hint
    (
        (0.80, 0.60), (0.88, 0.58), (0.94, 0.62), (0.96, 0.68), (0.92, 0.74),
        (0.86, 0.76), (0.80, 0.72), (0.78, 0.66), (0.80, 0.60),
    ),
    ((0.88, 0.78), (0.90, 0.78), (0.90, 0.80), (0.88, 0.80), (0.88, 0.78)),
    # New Zealand
    ((0.96, 0.72), (0.98, 0.70), (0.99, 0.74), (0.97, 0.78), (0.96, 0.74), (0.96, 0.72)),
    # Antarctica
    (
        (0.12, 0.88), (0.30, 0.86), (0.50, 0.84), (0.70, 0.86), (0.88, 0.88),
        (0.80, 0.94), (0.50, 0.96), (0.20, 0.94), (0.12, 0.88),
    ),
)

# (name, ux, uy) — real names parked on the refined crude map.
_SITES: tuple[tuple[str, float, float], ...] = (
    ("ICELAND", 0.44, 0.14),
    ("GREENLAND", 0.40, 0.12),
    ("CANADA", 0.22, 0.22),
    ("ALASKA", 0.08, 0.16),
    ("USA", 0.22, 0.34),
    ("MEXICO", 0.16, 0.46),
    ("CUBA", 0.28, 0.44),
    ("BRAZIL", 0.34, 0.60),
    ("ARGENTINA", 0.30, 0.78),
    ("PERU", 0.24, 0.60),
    ("UK", 0.48, 0.21),
    ("FRANCE", 0.50, 0.26),
    ("GERMANY", 0.54, 0.22),
    ("SPAIN", 0.47, 0.30),
    ("NORWAY", 0.53, 0.12),
    ("ITALY", 0.54, 0.34),
    ("GREECE", 0.57, 0.32),
    ("EGYPT", 0.58, 0.40),
    ("NIGERIA", 0.50, 0.48),
    ("KENYA", 0.60, 0.54),
    ("SOUTH AFRICA", 0.54, 0.72),
    ("TURKEY", 0.60, 0.30),
    ("RUSSIA", 0.74, 0.16),
    ("CHINA", 0.78, 0.34),
    ("JAPAN", 0.90, 0.32),
    ("INDIA", 0.70, 0.46),
    ("THAILAND", 0.78, 0.48),
    ("INDONESIA", 0.84, 0.55),
    ("AUSTRALIA", 0.88, 0.66),
    ("NEW ZEALAND", 0.97, 0.74),
    ("ANTARCTICA", 0.50, 0.90),
    ("MONGOLIA", 0.76, 0.26),
    ("KAZAKHSTAN", 0.66, 0.26),
    ("IRAN", 0.64, 0.36),
    ("SAUDI ARABIA", 0.62, 0.42),
    ("FIJI", 0.96, 0.58),
)

_PARABLES = (
    "MISSILES LAUNCHED: LEAVE APPROVED!",
    "TARGET NOT AUTHORIZED: SEABAG ONLY 1/2 FULL",
    "TARGET REJECTED: OUT TO LUNCH",
    "HOLD FIRE: COFFEE CALL IN PROGRESS",
    "WARHEAD DELAYED: FORM 27B INCOMPLETE",
    "SILO DOOR STUCK: TRY TURNING IT OFF AND ON",
    "RANGE SAFETY: BRING A JACKET",
    "IMPACT DEFERRED: TUESDAY IS LAUNDRY DAY",
    "TRACKING LOST: DUCK ENTERED RADAR",
    "ABORT CODE ACCEPTED: PIZZA ARRIVED",
    "TARGET REASSIGNED: NEAREST VENDING MACHINE",
    "LAUNCH WINDOW CLOSED: DOG NEEDS A WALK",
    "ORDERS CONFLICT: BOTH SIDES HAVE THE REMOTE",
    "DETONATION POSTPONED: BATTERY AT 12%",
    "FRIENDLY FIRE CHECK: IS THIS YOUR SANDWICH?",
    "GEOLOCK FAILED: MAP UPSIDE DOWN",
    "PRIORITY OVERRIDE: CAT ON THE CONSOLE",
    "STRIKE CANCELLED: NO PARKING AT TARGET",
)


@dataclass
class _Arc:
    i0: int
    i1: int
    t0: float
    dur: float
    bloom_until: float = 0.0


@dataclass
class _Round:
    launches: int = 0
    next_at: float = 0.0
    arcs: list[_Arc] = field(default_factory=list)
    last_target: int | None = None
    teletype: str = "SIMULATION ONLINE"
    text_until: float = _TEXT_HOLD
    pending_teletype: str | None = None
    parable: str | None = None
    parable_until: float = -1.0
    ending: bool = False
    end_until: float = -1.0


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _arc_point(x0, y0, x1, y1, t: float) -> tuple[float, float]:
    """Quadratic arc bulging away from the map midline."""
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    dist = max(8.0, ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5)
    # Bulge “up” on screen (smaller y) for a classic CRT missile trail.
    cx, cy = mx, my - dist * 0.35
    u = 1 - t
    return u * u * x0 + 2 * u * t * cx + t * t * x1, u * u * y0 + 2 * u * t * cy + t * t * y1


class GtwField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        self.pace = _BASE_PACE[values["speed"]]
        self.arc_dur = _ARC_DUR[values["speed"]]
        self.parable_chance = _PARABLE_CHANCE[values["parable"]]
        self.map_rgb = tuple(int(c) for c in np.asarray(settings.stops[0], dtype=np.float32) * settings.gain)
        self.missile_rgb = tuple(
            int(c) for c in np.asarray(settings.stops[1 % len(settings.stops)], dtype=np.float32) * settings.gain
        )
        self.site_rgbs = [
            tuple(int(min(255, c * settings.gain)) for c in _SITE_HUES[i % len(_SITE_HUES)])
            for i in range(len(_SITES))
        ]
        # Map rect: leave a teletype band at the bottom.
        self.band_h = max(7, height // 10)
        self.map_h = height - self.band_h
        self.map_w = width
        pad = max(1, min(width, self.map_h) // 32)
        self.ox, self.oy = pad, pad
        self.mw = width - 2 * pad
        self.mh = self.map_h - 2 * pad
        self._font_name = "tom-thumb" if min(width, height) < 96 else "5x7"
        self._font = None
        try:
            self._font = load_bdf(self._font_name)
        except FileNotFoundError:
            pass
        self._round = _Round(next_at=0.4)
        self._hit = np.zeros(len(_SITES), dtype=np.uint8)

    def _xy(self, ux: float, uy: float) -> tuple[int, int]:
        return int(self.ox + ux * self.mw), int(self.oy + uy * self.mh)

    def _pick_pair(self) -> tuple[int, int]:
        n = len(_SITES)
        # Prefer chaining off the last target; otherwise any launcher.
        if self._round.last_target is not None and self.rng.random() < 0.65:
            i0 = self._round.last_target
        else:
            i0 = int(self.rng.integers(0, n))
        # Bias absurd distance: sample a few candidates, take farthest.
        best_i1, best_d = i0, -1.0
        for _ in range(6):
            j = int(self.rng.integers(0, n))
            if j == i0:
                continue
            x0, y0 = _SITES[i0][1], _SITES[i0][2]
            x1, y1 = _SITES[j][1], _SITES[j][2]
            d = (x1 - x0) ** 2 + (y1 - y0) ** 2
            if d > best_d:
                best_d, best_i1 = d, j
        if best_i1 == i0:
            best_i1 = (i0 + 1 + int(self.rng.integers(0, n - 1))) % n
        return i0, best_i1

    def _set_teletype(self, t: float, line: str) -> None:
        """Show ``line`` now, or queue it if the current line still has hold time."""
        rnd = self._round
        if t >= rnd.text_until and t >= rnd.parable_until:
            rnd.teletype = line
            rnd.text_until = t + _TEXT_HOLD
            rnd.pending_teletype = None
        else:
            rnd.pending_teletype = line

    def _drain_teletype(self, t: float) -> None:
        rnd = self._round
        if rnd.pending_teletype and t >= rnd.text_until and t >= rnd.parable_until:
            rnd.teletype = rnd.pending_teletype
            rnd.pending_teletype = None
            rnd.text_until = t + _TEXT_HOLD

    def _launch(self, t: float) -> None:
        i0, i1 = self._pick_pair()
        self._round.arcs.append(
            _Arc(i0=i0, i1=i1, t0=t, dur=self.arc_dur, bloom_until=t + self.arc_dur + 0.55)
        )
        self._round.last_target = i1
        self._round.launches += 1
        a, b = _SITES[i0][0], _SITES[i1][0]
        self._set_teletype(t, f"LAUNCH: {a} -> {b}")
        # Mild acceleration — stay well under flight time so arcs stack up.
        factor = max(0.50, 0.96 ** self._round.launches)
        self._round.next_at = t + max(0.35, self.pace * factor)
        if self.rng.random() < self.parable_chance and t >= self._round.parable_until:
            self._round.parable = _PARABLES[int(self.rng.integers(0, len(_PARABLES)))]
            self._round.parable_until = t + _PARABLE_HOLD
            # Keep launch line queued underneath the parable.
            self._round.text_until = max(self._round.text_until, self._round.parable_until)
        if self._round.launches >= _MAX_LAUNCHES:
            self._round.ending = True
            self._round.end_until = t + self.arc_dur + 0.8 + _END_HOLD

    def _reset(self) -> None:
        self._round = _Round(next_at=0.5, text_until=_TEXT_HOLD)
        self._hit[:] = 0

    def _render_map(self, t: float) -> Image.Image:
        img = Image.new("RGB", (self.width, self.height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Continents.
        for poly in _CONTINENTS:
            pts = [self._xy(ux, uy) for ux, uy in poly]
            draw.line(pts + [pts[0]], fill=self.map_rgb, width=1)
        # Sites.
        r = 1 if self.width < 96 else 2
        for i, (_name, ux, uy) in enumerate(_SITES):
            x, y = self._xy(ux, uy)
            col = self.site_rgbs[i]
            if self._hit[i]:
                # Hit sites stay brighter / boxed.
                draw.rectangle((x - r - 1, y - r - 1, x + r + 1, y + r + 1), outline=col)
            draw.ellipse((x - r, y - r, x + r, y + r), fill=col)
        # Arcs + blooms.
        for arc in self._round.arcs:
            x0, y0 = self._xy(_SITES[arc.i0][1], _SITES[arc.i0][2])
            x1, y1 = self._xy(_SITES[arc.i1][1], _SITES[arc.i1][2])
            prog = (t - arc.t0) / max(0.05, arc.dur)
            if prog < 1.0:
                steps = max(28, int(64 * min(1.5, self.width / 64)))
                n = max(1, int(steps * min(1.0, prog)))
                pts = [_arc_point(x0, y0, x1, y1, i / steps) for i in range(n + 1)]
                if len(pts) >= 2:
                    draw.line([(int(p[0]), int(p[1])) for p in pts], fill=self.missile_rgb, width=1)
                hx, hy = pts[-1]
                draw.ellipse((int(hx) - 1, int(hy) - 1, int(hx) + 1, int(hy) + 1), fill=(255, 255, 255))
            else:
                if not self._hit[arc.i1]:
                    self._hit[arc.i1] = 1
                if t <= arc.bloom_until:
                    age = (t - (arc.t0 + arc.dur)) / 0.55
                    rad = int(_lerp(2, 7 + self.width // 36, min(1.0, age * 1.2)))
                    alpha = max(0.2, 1.0 - age)
                    bloom = tuple(int(c * alpha) for c in self.missile_rgb)
                    draw.ellipse((x1 - rad, y1 - rad, x1 + rad, y1 + rad), outline=bloom)
        # Teletype / parable band.
        band_y = self.map_h
        draw.rectangle((0, band_y, self.width, self.height), fill=(0, 0, 0))
        draw.line([(0, band_y), (self.width, band_y)], fill=self.map_rgb, width=1)
        text = self._round.teletype
        if self._round.parable and t < self._round.parable_until:
            text = self._round.parable
        self._draw_text(draw, text, band_y + 1)
        return img

    def _draw_text(self, draw, text: str, top: int) -> None:
        color = self.missile_rgb
        if self._font is None:
            draw.text((2, top), text[: max(8, self.width // 4)], fill=color)
            return
        # Scroll / truncate to width.
        tw, _ = text_size(self._font, text)
        if tw <= self.width - 2:
            draw_ink_centered(draw, self.width // 2, top, text, self._font, color)
            return
        # Left-align truncated with ellipsis feel: keep the end (orders matter).
        shown = text
        while len(shown) > 3 and text_size(self._font, shown)[0] > self.width - 2:
            shown = shown[1:]
        draw.text((1, top), shown, font=self._font, fill=color)

    def _render_end(self) -> Image.Image:
        img = Image.new("RGB", (self.width, self.height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        lines = ("WINNER:", "NONE POSSIBLE")
        color = self.missile_rgb
        if self._font is None:
            y = self.height // 3
            for line in lines:
                draw.text((4, y), line, fill=color)
                y += 12
            return img
        gap = 2 if self.height < 96 else 4
        heights = [text_size(self._font, line)[1] for line in lines]
        total = sum(heights) + gap * (len(lines) - 1)
        y = max(1, (self.height - total) // 2)
        for line, lh in zip(lines, heights):
            draw_ink_centered(draw, self.width // 2, y, line, self._font, color)
            y += lh + gap
        return img

    def frame(self, t: float, dt: float) -> np.ndarray:
        rnd = self._round
        if rnd.ending and t >= rnd.end_until - _END_HOLD:
            # Show end card for the hold window, then reset.
            if t >= rnd.end_until:
                self._reset()
            else:
                # Still finish in-flight blooms for a beat, then card.
                if t >= rnd.end_until - _END_HOLD + 0.35:
                    return np.asarray(self._render_end(), dtype=np.uint8)
        if not rnd.ending and t >= rnd.next_at:
            self._launch(t)
        self._drain_teletype(t)
        # Drop finished arcs that are done blooming (keep hits).
        rnd.arcs = [a for a in rnd.arcs if t <= a.bloom_until + 0.01 or (t - a.t0) < a.dur]
        return np.asarray(self._render_map(t), dtype=np.uint8)


class GtwMode(EffectMode):
    mode_id = "gtw"
    field_class = GtwField
    tick_interval = 0.04
