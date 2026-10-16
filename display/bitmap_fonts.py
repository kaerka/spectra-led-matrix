"""hzeller BDF bitmap fonts for Pillow rendering on small canvases.

TrueType blurs below ~10px on LEDs; the BDF fonts shipped with
rpi-rgb-led-matrix stay pixel-exact. Pillow cannot read BDF directly, so each
font is converted once to Pillow's .pil/.pbm format and cached.
"""

from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from pathlib import Path

from PIL import BdfFontFile, Image, ImageDraw, ImageFont

from display.matrix_config import DATA_ROOT


def font_dirs() -> list[Path]:
    dirs = []
    if os.environ.get("SPECTRA_FONT_DIR"):
        dirs.append(Path(os.environ["SPECTRA_FONT_DIR"]))
    dirs += [
        Path(DATA_ROOT) / "repos" / "rpi-rgb-led-matrix" / "fonts",
        Path.home() / "rpi-rgb-led-matrix" / "fonts",
    ]
    return dirs


def _cache_dir() -> Path:
    path = Path(tempfile.gettempdir()) / "spectra-bdf-cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


@lru_cache(maxsize=None)
def load_bdf(name: str) -> ImageFont.ImageFont:
    """Load e.g. "5x7" or "tom-thumb" from the first font dir that has it."""
    for d in font_dirs():
        src = d / f"{name}.bdf"
        if src.is_file():
            break
    else:
        raise FileNotFoundError(f"{name}.bdf not found in {[str(d) for d in font_dirs()]}")
    base = _cache_dir() / f"{name}-{int(src.stat().st_mtime)}"
    pil = base.with_suffix(".pil")
    if not pil.is_file():
        with src.open("rb") as fp:
            BdfFontFile.BdfFontFile(fp).save(str(base))
    return ImageFont.load(str(pil))


def text_size(font, text: str) -> tuple[int, int]:
    """Ink width and the font's full line height (stable across strings)."""
    left, _top, right, _bottom = font.getbbox(text)
    _l, top, _r, bottom = font.getbbox("Ayg|")
    return right - left, bottom - top


@lru_cache(maxsize=4096)
def ink_box(font, text: str) -> tuple[int, int, int, int]:
    """Lit-pixel bounds of text drawn at (0, 0); BDF cells include blank padding."""
    w, h = font.getbbox(text)[2:]
    img = Image.new("1", (max(1, w), max(1, h)))
    ImageDraw.Draw(img).text((0, 0), text, font=font, fill=1)
    return img.getbbox() or (0, 0, 0, 0)


def draw_ink_centered(draw, cx: int, top: int, text: str, font, color) -> int:
    """Draw text with its ink centred on cx and its top ink row at top; returns ink bottom."""
    x0, y0, x1, y1 = ink_box(font, text)
    draw.text((cx - (x1 - x0) // 2 - x0, top - y0), text, font=font, fill=color)
    return top + (y1 - y0)
