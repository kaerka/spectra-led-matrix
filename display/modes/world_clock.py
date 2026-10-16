"""World clock mode — spectra_clock (world-clock repo) on the 192x192 walls,
the built-in compact layout on smaller canvases."""

from __future__ import annotations

import os
import sys
from datetime import datetime

from rgbmatrix import RGBMatrix

from display.matrix import CANVAS_H, CANVAS_W
from display.modes.compact_clock import UTC, load_clock_settings, render_compact_clock
from display.pillow_compat import set_pillow_image

SPECTRA_DATA_ROOT = os.environ.get("SPECTRA_DATA_ROOT", "/data/spectra")
SPECTRA_CLOCK_DIR = os.path.normpath(
    os.path.join(SPECTRA_DATA_ROOT, "repos", "world-clock", "rpi4-electrodragon")
)
if not os.path.isdir(SPECTRA_CLOCK_DIR):
    SPECTRA_CLOCK_DIR = os.path.normpath(
        os.path.join(os.path.expanduser("~"), "world-clock", "rpi4-electrodragon")
    )


def _wall_renderer():
    if (CANVAS_W, CANVAS_H) != (192, 192):
        return None
    if SPECTRA_CLOCK_DIR not in sys.path:
        sys.path.insert(0, SPECTRA_CLOCK_DIR)
    import spectra_clock

    return lambda: spectra_clock.render_clock(datetime.now(spectra_clock.UTC))


class WorldClockMode:
    tick_interval = 0.5

    def setup(self, matrix: RGBMatrix) -> None:
        self._matrix = matrix
        render = _wall_renderer()
        if render is None:
            settings = load_clock_settings()
            render = lambda: render_compact_clock(  # noqa: E731
                datetime.now(UTC), CANVAS_W, CANVAS_H, settings)
        self._render = render

    def teardown(self) -> None:
        pass

    def tick(self, matrix: RGBMatrix, canvas):
        set_pillow_image(canvas, self._render())
        return matrix.SwapOnVSync(canvas)
