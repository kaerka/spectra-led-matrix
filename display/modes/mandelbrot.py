"""Mandelbrot zoom — slow dive into a deep point on the set boundary."""

from __future__ import annotations

import numpy as np

from display.modes.effect_base import EffectField, EffectMode, gradient_lut

_CENTER = (-0.743643887037151, 0.131825904205312)
_LUT_SIZE = 512
_ZOOM_RATE = (0.04, 0.08, 0.14, 0.22)  # decades per second (log10 shrink of view width)
_MAX_ITER = (40, 80, 120)
_VIEW0 = 2.8


def _palette_lut(settings) -> np.ndarray:
    gain = settings.gain
    if settings.continuous:
        return np.clip(gradient_lut(settings.stops, _LUT_SIZE) * gain, 0, 255).astype(np.uint8)
    stops = np.asarray(settings.stops, dtype=np.float32)
    idx = (np.arange(_LUT_SIZE) * len(stops) // _LUT_SIZE).astype(np.int32)
    return np.clip(stops[idx % len(stops)] * gain, 0, 255).astype(np.uint8)


def _mandelbrot(w: int, h: int, cx: float, cy: float, span_x: float, max_iter: int) -> np.ndarray:
    aspect = w / max(1, h)
    span_y = span_x / aspect
    y = np.linspace(cy - span_y / 2, cy + span_y / 2, h, dtype=np.float64)
    x = np.linspace(cx - span_x / 2, cx + span_x / 2, w, dtype=np.float64)
    c = x[np.newaxis, :] + 1j * y[:, np.newaxis]
    z = np.zeros_like(c)
    iters = np.zeros(c.shape, dtype=np.int32)
    mask = np.ones(c.shape, dtype=bool)
    for i in range(max_iter):
        z[mask] = z[mask] * z[mask] + c[mask]
        escaped = np.abs(z) > 2.0
        iters[escaped & mask] = i
        mask &= ~escaped
    return iters


class MandelbrotField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        self.zoom_rate = _ZOOM_RATE[values["speed"]]
        self.max_iter = _MAX_ITER[values["detail"]]
        self.lut = _palette_lut(settings)
        self.half = width >= 128

    def frame(self, t: float, dt: float) -> np.ndarray:
        span = _VIEW0 * (10.0 ** (-t * self.zoom_rate))
        rw, rh = self.width, self.height
        if self.half:
            rw, rh = max(1, self.width // 2), max(1, self.height // 2)
        it = _mandelbrot(rw, rh, _CENTER[0], _CENTER[1], span, self.max_iter)
        phase = (it.astype(np.float32) / max(1, self.max_iter - 1)) % 1.0
        small = self.lut[(phase * (_LUT_SIZE - 1)).astype(np.int32)]
        if not self.half:
            return small
        out = np.repeat(np.repeat(small, 2, axis=0), 2, axis=1)
        return out[: self.height, : self.width]


class MandelbrotMode(EffectMode):
    mode_id = "mandelbrot"
    field_class = MandelbrotField
    tick_interval = 0.05
