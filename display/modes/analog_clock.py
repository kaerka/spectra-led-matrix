"""Analog clock — ring, ticks and sweeping hands, scaled to the canvas.

Hands are drawn at SUPERSAMPLE x resolution and box-filtered down, so they stay
smooth at 64x64; numerals (128 px and up) use bitmap fonts at native size.
"""

from __future__ import annotations

import math
from datetime import datetime

from PIL import Image, ImageDraw

from display.bitmap_fonts import draw_ink_centered, ink_box, load_bdf
from display.matrix_config import CANVAS_H, CANVAS_W
from display.pillow_compat import set_pillow_image

SUPERSAMPLE = 4
RING_COLOR = (40, 50, 80)
HOUR_TICK_COLOR = (150, 160, 190)
QUARTER_TICK_COLOR = (255, 255, 255)
MINUTE_DOT_COLOR = (60, 70, 100)
NUMERAL_COLOR = (170, 180, 210)
DATE_COLOR = (110, 110, 110)
HOUR_HAND_COLOR = (255, 200, 120)
MINUTE_HAND_COLOR = (235, 235, 235)
SECOND_HAND_COLOR = (255, 40, 40)

NUMERAL_FONTS = ("7x13B", "6x10", "5x7")


def _polar(cx: float, cy: float, r: float, frac: float) -> tuple[float, float]:
    """frac 0..1 clockwise from 12 o'clock."""
    a = frac * 2 * math.pi
    return cx + r * math.sin(a), cy - r * math.cos(a)


def _thick_line(draw, p0, p1, width: float, color) -> None:
    w = max(1, round(width))
    draw.line((p0, p1), fill=color, width=w)
    r = w / 2
    for x, y in (p0, p1):
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color)


def render_face(size: int, now: datetime | None = None) -> Image.Image:
    """Static face at native resolution (date text, if any, uses `now`)."""
    ss = SUPERSAMPLE
    big = Image.new("RGB", (size * ss, size * ss))
    draw = ImageDraw.Draw(big)
    c = size * ss / 2
    r = c - ss * 0.5
    draw.ellipse((c - r, c - r, c + r, c + r), outline=RING_COLOR, width=ss)

    for i in range(60):
        frac = i / 60
        if i % 5:
            if size >= 128:
                x, y = _polar(c, c, r - ss * 3, frac)
                d = ss * 0.9
                draw.ellipse((x - d, y - d, x + d, y + d), fill=MINUTE_DOT_COLOR)
            continue
        quarter = i % 15 == 0
        length = size * (0.11 if quarter else 0.07) * ss
        width = ss * (2 if quarter and size >= 64 else 1) * max(1, size // 96)
        _thick_line(draw, _polar(c, c, r - ss * 1.5, frac),
                    _polar(c, c, r - ss * 1.5 - length, frac), width,
                    QUARTER_TICK_COLOR if quarter else HOUR_TICK_COLOR)

    face = big.resize((size, size), Image.BOX)
    if size >= 128:
        fdraw = ImageDraw.Draw(face)
        font = load_bdf(NUMERAL_FONTS[0] if size >= 160 else NUMERAL_FONTS[1])
        num_r = size / 2 * 0.70
        for n in range(1, 13):
            x, y = _polar(size / 2, size / 2, num_r, n / 12)
            _x0, y0, _x1, y1 = ink_box(font, str(n))
            draw_ink_centered(fdraw, round(x), round(y - (y1 - y0) / 2), str(n), font, NUMERAL_COLOR)
        if now is not None:
            small = load_bdf("5x7")
            draw_ink_centered(fdraw, size // 2, round(size / 2 + size * 0.2),
                              now.strftime("%a %d").upper(), small, DATE_COLOR)
    return face


def render_hands(size: int, now: datetime) -> Image.Image:
    """RGBA hands layer at native resolution."""
    ss = SUPERSAMPLE
    layer = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    c = size * ss / 2
    r = c
    sec = now.second + now.microsecond / 1e6
    minute = now.minute + sec / 60
    hour = (now.hour % 12) + minute / 60
    unit = size * ss / 64  # 1 native px on a 64 px face

    _thick_line(draw, _polar(c, c, -r * 0.08, hour / 12), _polar(c, c, r * (0.50 if size < 128 else 0.44), hour / 12),
                unit * 3.0, HOUR_HAND_COLOR + (255,))
    _thick_line(draw, _polar(c, c, -r * 0.08, minute / 60), _polar(c, c, r * 0.78, minute / 60),
                unit * 2.0, MINUTE_HAND_COLOR + (255,))
    _thick_line(draw, _polar(c, c, -r * 0.18, sec / 60), _polar(c, c, r * 0.86, sec / 60),
                max(ss, unit * 0.9), SECOND_HAND_COLOR + (255,))
    cap = unit * 2.2
    draw.ellipse((c - cap, c - cap, c + cap, c + cap), fill=SECOND_HAND_COLOR + (255,))
    return layer.resize((size, size), Image.BOX)


def render_analog_clock(now: datetime, width: int, height: int,
                        face: Image.Image | None = None) -> Image.Image:
    size = min(width, height)
    face = face if face is not None else render_face(size, now)
    dial = Image.alpha_composite(face.convert("RGBA"), render_hands(size, now)).convert("RGB")
    out = Image.new("RGB", (width, height))
    out.paste(dial, ((width - size) // 2, (height - size) // 2))
    return out


class AnalogClockMode:
    tick_interval = 0.05

    def setup(self, matrix) -> None:
        self._face = None
        self._face_day = None

    def teardown(self) -> None:
        pass

    def tick(self, matrix, canvas):
        now = datetime.now()
        if self._face_day != now.date():
            self._face = render_face(min(CANVAS_W, CANVAS_H), now)
            self._face_day = now.date()
        set_pillow_image(canvas, render_analog_clock(now, CANVAS_W, CANVAS_H, self._face))
        return matrix.SwapOnVSync(canvas)
