"""Runtime shared by the procedural effects in ``effect_config``."""

from __future__ import annotations

import time
from typing import Sequence

import numpy as np
from PIL import Image

from display.matrix_config import CANVAS_H, CANVAS_W
from display.modes.effect_config import Color, EffectSettings, resolve_effect
from display.pillow_compat import set_pillow_image
from display.state import load_state


def gradient_lut(stops: Sequence[Color], size: int = 1024) -> np.ndarray:
    """(size, 3) float32 colours looping through ``stops`` and back to the first."""
    pts = np.asarray(stops, dtype=np.float32)
    pos = np.arange(size, dtype=np.float32) * len(pts) / size
    idx = pos.astype(int)
    frac = (pos - idx)[:, None]
    return pts[idx % len(pts)] * (1 - frac) + pts[(idx + 1) % len(pts)] * frac


class EffectField:
    """One effect's simulation; ``frame`` returns an (h, w, 3) uint8 array."""

    def __init__(self, width: int, height: int, settings: EffectSettings, seed=None) -> None:
        self.width, self.height = width, height
        self.settings = settings
        self.rng = np.random.default_rng(seed)

    def frame(self, t: float, dt: float) -> np.ndarray:
        raise NotImplementedError


class EffectMode:
    mode_id = ""
    field_class = EffectField
    tick_interval = 0.03

    def setup(self, matrix) -> None:
        state = load_state()
        cfg = (state.mode_config or {}).get(self.mode_id)
        settings = resolve_effect(self.mode_id, cfg if isinstance(cfg, dict) else None)
        self._field = self.field_class(CANVAS_W, CANVAS_H, settings)
        self._start = self._last = time.monotonic()

    def teardown(self) -> None:
        pass

    def tick(self, matrix, canvas):
        now = time.monotonic()
        dt = min(0.1, now - self._last)
        self._last = now
        frame = self._field.frame(now - self._start, dt)
        set_pillow_image(canvas, Image.fromarray(frame))
        return matrix.SwapOnVSync(canvas)
