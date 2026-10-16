"""Word-wrap and scroll rendering for MQTT message overlay."""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from display.matrix import CANVAS_H, CANVAS_W

BORDER_COLOR = (0x20, 0x20, 0x20)
DEJAVU = "/usr/share/fonts/truetype/dejavu"
REFERENCE_PX = 192
MIN_FONT_PX = 8
_SCRATCH = ImageDraw.Draw(Image.new("RGB", (1, 1)))


def scaled_font_size(base: int, width: int, height: int) -> int:
    """Font sizes are configured for the 192x192 wall; shrink them on smaller canvases."""
    scale = min(width, height) / REFERENCE_PX
    return max(MIN_FONT_PX, min(base, round(base * scale)))


def message_font(size: int = 18) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(f"{DEJAVU}/DejaVuSans-Bold.ttf", size)


def _line_height(font) -> int:
    bbox = _SCRATCH.textbbox((0, 0), "Ayg", font=font)
    return (bbox[3] - bbox[1]) + 1


def _split_long_word(word: str, font, max_w: int) -> list[str]:
    chunks: list[str] = []
    chunk = ""
    for ch in word:
        if not chunk or _SCRATCH.textlength(chunk + ch, font=font) <= max_w:
            chunk += ch
        else:
            chunks.append(chunk)
            chunk = ch
    if chunk:
        chunks.append(chunk)
    return chunks


def wrap_text(text: str, font, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            tokens = (
                [word]
                if _SCRATCH.textlength(word, font=font) <= max_w
                else _split_long_word(word, font, max_w)
            )
            for tok in tokens:
                trial = tok if not cur else cur + " " + tok
                if _SCRATCH.textlength(trial, font=font) <= max_w:
                    cur = trial
                else:
                    lines.append(cur)
                    cur = tok
        lines.append(cur)
    return lines


def build_message_image(
    text: str, font, color: tuple[int, int, int], max_w: int
) -> Image.Image:
    lines = wrap_text(text, font, max_w)
    line_h = _line_height(font)
    img = Image.new("RGB", (max_w, max(1, line_h * len(lines))), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    y = 0
    for ln in lines:
        w = _SCRATCH.textlength(ln, font=font)
        draw.text((max(0, (max_w - w) // 2), y), ln, font=font, fill=color)
        y += line_h
    return img


def render_message_frame(
    tall: Image.Image,
    elapsed: float,
    scroll_pps: float,
) -> Image.Image:
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, CANVAS_W - 1, CANVAS_H - 1), outline=BORDER_COLOR)
    inner_w, inner_h = CANVAS_W - 2, CANVAS_H - 2
    inner = Image.new("RGB", (inner_w, inner_h), (0, 0, 0))
    content_h = tall.height
    if content_h <= inner_h:
        inner.paste(tall, (0, (inner_h - content_h) // 2))
    else:
        period = content_h + inner_h
        off = int(elapsed * scroll_pps) % period
        inner.paste(tall, (0, -off))
        inner.paste(tall, (0, -off + period))
    img.paste(inner, (1, 1))
    return img
