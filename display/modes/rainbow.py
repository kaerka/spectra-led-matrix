"""Rainbow — colour bands flowing diagonally from one corner to the opposite one."""

from __future__ import annotations

import numpy as np

from display.modes.effect_base import EffectField, EffectMode, gradient_lut

LUT_SIZE = 1024
# Pattern travel in full colour cycles per second, per speed level.
_CYCLES_PER_SEC = (0.03, 0.08, 0.2, 0.5)
# Full colour cycles visible along the diagonal, per band setting.
_BANDS = (1.0, 2.0, 4.0)


class RainbowField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        y, x = np.mgrid[0:height, 0:width].astype(np.float32)
        direction = values["direction"]
        if direction in (1, 2):
            x = (width - 1) - x
        if direction in (2, 3):
            y = (height - 1) - y
        # 0 at the start corner, 1 at the opposite corner.
        diag = (x + y) / max(1, (width - 1) + (height - 1))
        self.pos = diag * _BANDS[values["bands"]]
        self.hz = _CYCLES_PER_SEC[values["speed"]]
        self.lut = np.clip(gradient_lut(settings.stops, LUT_SIZE) * settings.gain, 0, 255).astype(np.uint8)

    def frame(self, t: float, dt: float) -> np.ndarray:
        phase = (self.pos - t * self.hz) % 1.0
        return self.lut[(phase * LUT_SIZE).astype(np.int32) % LUT_SIZE]


class RainbowMode(EffectMode):
    mode_id = "rainbow"
    field_class = RainbowField
