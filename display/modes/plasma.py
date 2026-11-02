"""Plasma — classic demoscene colour fields summed into a palette LUT."""

from __future__ import annotations

import numpy as np

from display.modes.effect_base import EffectField, EffectMode, gradient_lut

_LUT_SIZE = 256
_HZ = (0.25, 0.55, 1.0, 1.8)
_FREQ = (0.04, 0.08, 0.16)  # Wide, Medium, Tight — spatial frequency scale


def _palette_lut(settings) -> np.ndarray:
    gain = settings.gain
    if settings.continuous:
        return np.clip(gradient_lut(settings.stops, _LUT_SIZE) * gain, 0, 255).astype(np.uint8)
    stops = np.asarray(settings.stops, dtype=np.float32)
    idx = (np.arange(_LUT_SIZE) * len(stops) // _LUT_SIZE).astype(np.int32)
    return np.clip(stops[idx % len(stops)] * gain, 0, 255).astype(np.uint8)


class PlasmaField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        self.hz = _HZ[values["speed"]]
        self.freq = _FREQ[values["scale"]] * (128.0 / max(width, height))
        y, x = np.mgrid[0:height, 0:width].astype(np.float32)
        self.xs = x
        self.ys = y
        self.cx = (width - 1) / 2.0
        self.cy = (height - 1) / 2.0
        self.lut = _palette_lut(settings)

    def frame(self, t: float, dt: float) -> np.ndarray:
        f = self.freq
        w = t * self.hz * 2 * np.pi
        r = np.sqrt((self.xs - self.cx) ** 2 + (self.ys - self.cy) ** 2) + 1.0
        v = (
            np.sin(self.xs * f + w)
            + np.sin(self.ys * f * 1.1 + w * 0.9)
            + np.sin((self.xs + self.ys) * f * 0.55 + w * 1.4)
            + np.sin(r * f * 0.85 + w * 0.7)
        )
        phase = ((v + 4.0) / 8.0) % 1.0
        return self.lut[(phase * (_LUT_SIZE - 1)).astype(np.int32)]


class PlasmaMode(EffectMode):
    mode_id = "plasma"
    field_class = PlasmaField
    tick_interval = 0.033
