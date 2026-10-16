"""Render a 1-3 line custom message to fit any canvas size.

Sizes are symbolic and scaled to the canvas; if the wrapped text does not fit,
every line shrinks together (keeping their relative sizes) down to a legible
minimum, and only then does the message scroll vertically.

Takes the canvas size as arguments instead of importing display.matrix, so it
renders off-device (tests, the HAT mini, previews).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
BORDER_COLOR = (0x20, 0x20, 0x20)
# Pixel heights on the 192x192 wall; scaled by min(width, height) / 192.
SIZE_PX = {"small": 16, "medium": 22, "large": 30}
REFERENCE_PX = 192
MIN_FONT_PX = 7
PAD = 2
BORDER_MIN_PX = 96

_SCRATCH = ImageDraw.Draw(Image.new("RGB", (1, 1)))


@lru_cache(maxsize=64)
def _font(px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, px)


def _line_height(font) -> int:
    bbox = _SCRATCH.textbbox((0, 0), "Ayg", font=font)
    return bbox[3] - bbox[1] + 1


def _fits(text: str, font, max_w: int) -> bool:
    return _SCRATCH.textlength(text, font=font) <= max_w


def wrap(text: str, font, max_w: int) -> List[str]:
    rows: List[str] = []
    cur = ""
    for word in text.split():
        pieces = [word]
        if not _fits(word, font, max_w):
            pieces, chunk = [], ""
            for ch in word:
                if chunk and not _fits(chunk + ch, font, max_w):
                    pieces.append(chunk)
                    chunk = ""
                chunk += ch
            pieces.append(chunk)
        for piece in pieces:
            trial = f"{cur} {piece}" if cur else piece
            if _fits(trial, font, max_w):
                cur = trial
            else:
                rows.append(cur)
                cur = piece
    if cur or not rows:
        rows.append(cur)
    return rows


def _layout(lines: Sequence[Dict[str, Any]], scale: float, max_w: int):
    blocks = []
    for line in lines:
        px = max(MIN_FONT_PX, int(round(SIZE_PX.get(line["size"], SIZE_PX["medium"]) * scale)))
        font = _font(px)
        rows = wrap(line["text"], font, max_w) if line["text"] else [""]
        blocks.append((font, rows, tuple(line["color"])))
    gap = max(1, int(round(3 * scale)))
    height = sum(_line_height(f) * len(rows) for f, rows, _ in blocks) + gap * (len(blocks) - 1)
    return blocks, gap, height


def _pad(width: int, height: int) -> int:
    """Small panels can't spare pixels for the border, so they get none."""
    return PAD if min(width, height) >= BORDER_MIN_PX else 1


def fit_layout(lines: Sequence[Dict[str, Any]], width: int, height: int):
    """Largest scale (<= the size's nominal one) at which the message fits."""
    pad = _pad(width, height)
    max_w = width - 2 * pad
    max_h = height - 2 * pad
    scale = min(width, height) / REFERENCE_PX
    smallest = MIN_FONT_PX / min(SIZE_PX[line["size"]] for line in lines)
    while True:
        blocks, gap, content_h = _layout(lines, scale, max_w)
        if content_h <= max_h or scale <= smallest:
            return blocks, gap, content_h, scale
        scale = max(smallest, scale * 0.9)


def build_content(lines: Sequence[Dict[str, Any]], width: int, height: int) -> Image.Image:
    """The message laid out at full width; taller than the canvas only if it must scroll."""
    blocks, gap, content_h, _scale = fit_layout(lines, width, height)
    inner_w = width - 2 * _pad(width, height)
    img = Image.new("RGB", (inner_w, max(1, content_h)), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    y = 0
    for n, (font, rows, color) in enumerate(blocks):
        line_h = _line_height(font)
        top = _SCRATCH.textbbox((0, 0), "Ayg", font=font)[1]
        for row in rows:
            w = _SCRATCH.textlength(row, font=font)
            draw.text((max(0, (inner_w - w) // 2), y - top), row, font=font, fill=color)
            y += line_h
        if n < len(blocks) - 1:
            y += gap
    return img


def compose_frame(content: Image.Image, width: int, height: int,
                  elapsed: float, scroll_pps: float = 12.0) -> Image.Image:
    frame = Image.new("RGB", (width, height), (0, 0, 0))
    pad = _pad(width, height)
    if pad == PAD:
        ImageDraw.Draw(frame).rectangle((0, 0, width - 1, height - 1), outline=BORDER_COLOR)
    inner_h = height - 2 * pad
    if content.height <= inner_h:
        frame.paste(content, (pad, pad + (inner_h - content.height) // 2))
        return frame
    inner = Image.new("RGB", (content.width, inner_h), (0, 0, 0))
    period = content.height + inner_h
    off = int(elapsed * scroll_pps) % period
    inner.paste(content, (0, -off))
    inner.paste(content, (0, -off + period))
    frame.paste(inner, (pad, pad))
    return frame


def render_message(message: Dict[str, Any], size: Tuple[int, int],
                   elapsed: float = 0.0) -> Image.Image:
    """One-shot render (previews and tests)."""
    width, height = size
    return compose_frame(build_content(message["lines"], width, height), width, height, elapsed)
