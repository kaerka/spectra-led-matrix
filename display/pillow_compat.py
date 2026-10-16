"""Pillow ↔ rgbmatrix SetImage compatibility.

hzeller's rgbmatrix bindings use Pillow's internal ``unsafe_ptrs`` API for fast
blits. That was removed in Pillow 10+, so newer venv installs crash with:

    AttributeError: 'ImagingCore' object has no attribute 'unsafe_ptrs'

System Python on the Pis still ships Pillow 9.x, which is why the legacy scripts
work. We try the fast path first, then fall back to ``unsafe=False``.
"""

from __future__ import annotations

from PIL import Image


def set_pillow_image(target, image: Image.Image, offset_x: int = 0, offset_y: int = 0) -> None:
    if image.mode != "RGB":
        image = image.convert("RGB")
    try:
        target.SetImage(image, offset_x, offset_y, unsafe=True)
    except AttributeError:
        target.SetImage(image, offset_x, offset_y, unsafe=False)
