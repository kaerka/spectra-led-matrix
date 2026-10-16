"""World clock layout for small canvases (one to four 64x64 panels).

The 192x192 walls use spectra_clock from the world-clock repo; this follows the
MatrixPortal S3 64x64 design (title, then stacked city label + time blocks) and
picks the largest bitmap fonts that fit whatever canvas it is given.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

from display.bitmap_fonts import draw_ink_centered, ink_box, load_bdf
from display.matrix_config import DATA_ROOT

UTC = ZoneInfo("UTC")
TITLE_COLOR = (0xFF, 0xAA, 0x00)
LABEL_COLOR = (0x30, 0x60, 0xFF)
BORDER_COLOR = (0x30, 0x30, 0x30)

TITLE_FONTS = ("7x13B", "6x10", "5x7", "tom-thumb")
LABEL_FONTS = ("6x10", "5x7", "tom-thumb")
TIME_FONTS = ("9x18B", "8x13B", "7x13B", "6x13B", "6x10", "5x7")


@dataclass(frozen=True)
class Zone:
    label: str
    color: tuple[int, int, int]
    tz: ZoneInfo


@dataclass(frozen=True)
class ClockSettings:
    title: str = "WORLD CLOCK"
    blink: bool = True
    zones: tuple[Zone, ...] = (
        Zone("HOME", (0x00, 0xFF, 0x66), ZoneInfo("UTC")),
        Zone("WEST", (0xFF, 0x80, 0x00), ZoneInfo("America/Los_Angeles")),
        Zone("EAST", (0xFF, 0x30, 0x30), ZoneInfo("Europe/Berlin")),
    )


def _config_paths() -> list[Path]:
    repo = Path(__file__).resolve().parents[2]
    return [Path(DATA_ROOT) / "config" / "clock.local.json", repo / "config" / "clock.local.json"]


def load_clock_settings() -> ClockSettings:
    for path in _config_paths():
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            break
    else:
        return ClockSettings()
    default = ClockSettings()
    zones = tuple(
        Zone(str(z["label"]), tuple(z.get("color", (255, 255, 255))), ZoneInfo(z["tz"]))
        for z in raw.get("zones", [])
    ) or default.zones
    return ClockSettings(
        title=str(raw.get("title", default.title)),
        blink=bool(raw.get("blink", default.blink)),
        zones=zones,
    )


def _ink_h(font, text: str) -> int:
    _x0, y0, _x1, y1 = ink_box(font, text)
    return y1 - y0


def _ink_w(font, text: str) -> int:
    x0, _y0, x1, _y1 = ink_box(font, text)
    return x1 - x0


def _pick(names, max_w: int, max_h: int, *samples: str):
    """Largest font whose ink fits; falls back to the smallest."""
    fonts = [load_bdf(n) for n in names]
    for font in fonts:
        if all(_ink_w(font, s) <= max_w and _ink_h(font, s) <= max_h for s in samples):
            return font
    return fonts[-1]


@dataclass(frozen=True)
class _Layout:
    border: bool
    title_font: object
    title_top: int
    label_font: object
    time_font: object
    block_top: int
    block_h: int
    label_gap: int


def _layout(width: int, height: int, settings: ClockSettings) -> _Layout:
    border = min(width, height) >= 48
    pad = 2 if border else 0
    inner_w = width - 2 * pad - 2
    title_font = _pick(TITLE_FONTS, inner_w, max(5, height // 9), settings.title)
    title_top = pad
    title_h = _ink_h(title_font, settings.title) if settings.title else -2
    block_top = title_top + title_h + 2
    n = max(1, len(settings.zones))
    block_h = (height - pad - block_top) // n
    labels = [z.label for z in settings.zones]
    label_font = _pick(LABEL_FONTS, inner_w, max(5, block_h // 3), *labels)
    label_h = max(_ink_h(label_font, s) for s in labels)
    label_gap = 2 if block_h - label_h >= 14 else 1
    time_font = _pick(TIME_FONTS, inner_w, block_h - label_h - label_gap - 1, "00:00")
    return _Layout(border, title_font, title_top, label_font, time_font,
                   block_top, block_h, label_gap)


def render_compact_clock(now_utc: datetime, width: int, height: int,
                         settings: ClockSettings | None = None) -> Image.Image:
    settings = settings or ClockSettings()
    lay = _layout(width, height, settings)
    img = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = width // 2
    if lay.border:
        draw.rectangle((0, 0, width - 1, height - 1), outline=BORDER_COLOR)
    if settings.title:
        draw_ink_centered(draw, cx, lay.title_top, settings.title, lay.title_font, TITLE_COLOR)

    colon = ":" if (not settings.blink or now_utc.second % 2) else " "
    label_h = max(_ink_h(lay.label_font, z.label) for z in settings.zones)
    time_h = _ink_h(lay.time_font, "00:00")
    content_h = label_h + lay.label_gap + time_h
    for i, zone in enumerate(settings.zones):
        top = lay.block_top + i * lay.block_h + (lay.block_h - content_h) // 2
        local = now_utc.astimezone(zone.tz)
        draw_ink_centered(draw, cx, top, zone.label, lay.label_font, LABEL_COLOR)
        tstr = f"{local.hour:02d}{colon}{local.minute:02d}"
        # Ink-centre on "00:00" so the blinking colon does not shift the digits.
        x0, y0, x1, _ = ink_box(lay.time_font, "00:00")
        draw.text((cx - (x1 - x0) // 2 - x0, top + label_h + lay.label_gap - y0),
                  tstr, font=lay.time_font, fill=zone.color)
    return img


if __name__ == "__main__":
    import sys

    w, h = (int(v) for v in (sys.argv[1:3] or (64, 64)))
    out = sys.argv[3] if len(sys.argv) > 3 else f"/tmp/compact_clock_{w}x{h}.png"
    render_compact_clock(datetime.now(UTC), w, h, load_clock_settings()).save(out)
    print(out, os.path.getsize(out))
