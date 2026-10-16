"""Weather layout for small canvases (the 192x192 wall layout lives in weather.py)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PIL import Image, ImageDraw

from display.bitmap_fonts import draw_ink_centered, ink_box, load_bdf

TIME_COLOR = (0xFF, 0xFF, 0xFF)
DATE_COLOR = (0x80, 0x80, 0x80)
TEMP_COLOR = (0xFF, 0xFF, 0xFF)
COND_COLOR = (0x40, 0x80, 0xFF)
MAX_COLOR = (0xFF, 0x00, 0xFF)
MIN_COLOR = (0xFF, 0xA5, 0x00)
HUMID_COLOR = (0x00, 0xFF, 0x00)
DIVIDER_COLOR = (0x30, 0x30, 0x30)
ERROR_COLOR = (0xFF, 0x30, 0x30)

TIME_FONTS = ("8x13B", "7x13B", "6x10", "5x7")
TEMP_FONTS = ("9x18B", "8x13B", "7x13B", "6x10")
SMALL_FONTS = ("6x10", "5x7", "tom-thumb")


@dataclass(frozen=True)
class WeatherReading:
    temp: float
    temp_max: float
    temp_min: float
    humidity: int
    condition: str

    @classmethod
    def from_openweathermap(cls, data: dict) -> "WeatherReading":
        main = data["main"]
        return cls(
            temp=float(main["temp"]),
            temp_max=float(main["temp_max"]),
            temp_min=float(main["temp_min"]),
            humidity=int(main["humidity"]),
            condition=str(data["weather"][0]["main"]),
        )


def _w(font, text):
    x0, _, x1, _ = ink_box(font, text)
    return x1 - x0


def _h(font, text):
    _, y0, _, y1 = ink_box(font, text)
    return y1 - y0


def _fit(names, max_w, max_h, text):
    fonts = [load_bdf(n) for n in names]
    for font in fonts:
        if _w(font, text) <= max_w and _h(font, text) <= max_h:
            return font
    return fonts[-1]


def render_compact_weather(now: datetime, reading: WeatherReading | None,
                           width: int, height: int) -> Image.Image:
    img = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = width // 2
    max_w = width - 4
    unit = height / 64

    tstr = now.strftime("%H:%M")
    time_font = _fit(TIME_FONTS, max_w, int(10 * unit), tstr)
    y = draw_ink_centered(draw, cx, 1, tstr, time_font, TIME_COLOR) + 2
    dstr = now.strftime("%a %d %b").upper()
    small = _fit(SMALL_FONTS, max_w, int(6 * unit), dstr)
    y = draw_ink_centered(draw, cx, y, dstr, small, DATE_COLOR) + 2
    draw.line((2, y, width - 3, y), fill=DIVIDER_COLOR)
    y += 3

    if reading is None:
        draw_ink_centered(draw, cx, y + 4, "NO DATA", small, ERROR_COLOR)
        return img

    temp = f"{round(reading.temp)}°"
    rows = [
        (reading.condition.upper(), COND_COLOR),
        (f"H{round(reading.temp_max)} L{round(reading.temp_min)}", None),
        (f"RH {reading.humidity}%", HUMID_COLOR),
    ]
    row_h = max(_h(small, t) for t, _ in rows) + 2
    temp_font = _fit(TEMP_FONTS, max_w, height - y - len(rows) * row_h - 2, temp)
    y = draw_ink_centered(draw, cx, y, temp, temp_font, TEMP_COLOR) + 3

    cond, hilo, humid = rows
    draw_ink_centered(draw, cx, y, cond[0], small, cond[1])
    y += row_h
    # High in the max colour, low in the min colour, centred as one string.
    hi, lo = hilo[0].split(" ")
    x0, y0, _, _ = ink_box(small, hilo[0])
    left = cx - _w(small, hilo[0]) // 2 - x0
    draw.text((left, y - y0), hi, font=small, fill=MAX_COLOR)
    draw.text((left + int(small.getlength(hi + " ")), y - y0), lo, font=small, fill=MIN_COLOR)
    y += row_h
    draw_ink_centered(draw, cx, y, humid[0], small, humid[1])
    return img
