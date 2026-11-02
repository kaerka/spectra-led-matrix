"""Mandelbrot zoom — dives into famous boundary points, fades, and moves on.

Frames are resampled from a slightly larger keyframe; the next keyframe is
computed a few rows per tick, so cost per frame stays flat as the zoom deepens.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image

from display.modes.effect_base import EffectField, EffectMode, gradient_lut

# (centre x, centre y, decades of zoom that stay interesting at our iteration budget)
_TARGETS = (
    (-0.743643887037151, 0.131825904205312, 5.0),
    (-0.101096363845620, 0.956286510809140, 8.0),
    (-0.775683770000000, 0.136467370000000, 6.5),
    (0.360240443437614, -0.641313061064803, 8.0),
)
_LUT_SIZE = 512
_ZOOM_RATE = (0.06, 0.10, 0.16, 0.25)  # decades per second
_BASE_ITER = (48, 80, 120)
_ITER_PER_DECADE = (16, 28, 40)
_VIEW0 = 3.0
_STEP = 1.3  # zoom between keyframes
_LEAD = 1.6  # finish the next keyframe by ~60% of the way to it
_FADE_S = 1.2
_BAILOUT = 256.0
_BAND = 24.0  # iterations per palette loop


def _escape(xs: np.ndarray, ys: np.ndarray, max_iter: int) -> np.ndarray:
    """Smooth escape count for the grid ``ys x xs``; -1 for points inside the set."""
    h, w = len(ys), len(xs)
    x = np.broadcast_to(xs[None, :], (h, w)).ravel()
    y = np.broadcast_to(ys[:, None], (h, w)).ravel()
    out = np.full(h * w, -1.0, dtype=np.float32)

    xq = x - 0.25
    q = xq * xq + y * y
    inside = (q * (q + xq) <= 0.25 * y * y) | ((x + 1.0) ** 2 + y * y <= 0.0625)
    idx = np.flatnonzero(~inside)
    cr, ci = x[idx], y[idx]
    zr = np.zeros_like(cr)
    zi = np.zeros_like(ci)
    for i in range(max_iter):
        zr2, zi2 = zr * zr, zi * zi
        zi = 2.0 * zr * zi + ci
        zr = zr2 - zi2 + cr
        mag = zr * zr + zi * zi
        esc = mag > _BAILOUT
        if esc.any():
            out[idx[esc]] = i + 1 - np.log2(0.5 * np.log(mag[esc]))
            keep = ~esc
            idx, cr, ci, zr, zi = idx[keep], cr[keep], ci[keep], zr[keep], zi[keep]
            if idx.size == 0:
                break
    return out.reshape(h, w)


class _Keyframe:
    def __init__(self, cx: float, cy: float, span: float, kw: int, kh: int, max_iter: int) -> None:
        self.span = span
        step = span / kw
        self.xs = cx + (np.arange(kw, dtype=np.float64) - (kw - 1) / 2) * step
        self.ys = cy + (np.arange(kh, dtype=np.float64) - (kh - 1) / 2) * step
        self.max_iter = max_iter
        self.v = np.empty((kh, kw), dtype=np.float32)
        self.rows = 0

    @property
    def done(self) -> bool:
        return self.rows >= len(self.ys)

    def compute_to(self, rows: int) -> None:
        rows = min(rows, len(self.ys))
        if rows > self.rows:
            self.v[self.rows : rows] = _escape(self.xs, self.ys[self.rows : rows], self.max_iter)
            self.rows = rows


class MandelbrotField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        self.zoom_rate = _ZOOM_RATE[values["speed"]]
        self.base_iter = _BASE_ITER[values["detail"]]
        self.iter_per_decade = _ITER_PER_DECADE[values["detail"]]
        self.lut = np.clip(gradient_lut(settings.stops, _LUT_SIZE) * settings.gain, 0, 255).astype(np.uint8)
        self.kw = 128 if width >= 128 else width + 16
        self.kh = max(1, int(round(self.kw * height / width)))
        self.target = int(self.rng.integers(len(_TARGETS)))
        self._start_cycle(0.0)

    def _make_key(self, span: float) -> _Keyframe:
        cx, cy, _ = _TARGETS[self.target]
        decades = math.log10(_VIEW0 / span)
        max_iter = int(self.base_iter + self.iter_per_decade * decades)
        return _Keyframe(cx, cy, span, self.kw, self.kh, max_iter)

    def _start_cycle(self, t: float) -> None:
        self.cycle_start = t
        self.duration = _TARGETS[self.target][2] / self.zoom_rate
        self.key = self._make_key(_VIEW0)
        self.key.compute_to(self.kh)
        self.next = self._make_key(_VIEW0 / _STEP)

    def frame(self, t: float, dt: float) -> np.ndarray:
        local = t - self.cycle_start
        if local >= self.duration:
            self.target = (self.target + 1) % len(_TARGETS)
            self._start_cycle(t)
            local = 0.0
        span = _VIEW0 * 10.0 ** (-local * self.zoom_rate)

        if span <= self.next.span:
            self.next.compute_to(self.kh)
            self.key, self.next = self.next, self._make_key(self.next.span / _STEP)
        progress = math.log(self.key.span / span) / math.log(_STEP)
        self.next.compute_to(math.ceil(self.kh * min(1.0, progress * _LEAD)))

        v = self.key.v
        inside = v < 0
        if local > _FADE_S and self.duration - local > _FADE_S and inside.mean() > 0.7:
            self.duration = local + _FADE_S
        phase = (np.sqrt(np.maximum(v, 0.0)) * (_LUT_SIZE * 4.0 / _BAND) + t * 40.0) % _LUT_SIZE
        rgb = self.lut[phase.astype(np.int32)]
        rgb[inside] = 0

        frac = span / self.key.span
        x0, y0 = self.kw * (1 - frac) / 2, self.kh * (1 - frac) / 2
        img = Image.fromarray(rgb).transform(
            (self.width, self.height),
            Image.EXTENT,
            (x0, y0, self.kw - x0, self.kh - y0),
            Image.BILINEAR,
        )
        out = np.asarray(img)
        fade = min(1.0, local / _FADE_S, (self.duration - local) / _FADE_S)
        if fade < 1.0:
            out = (out.astype(np.float32) * max(0.0, fade)).astype(np.uint8)
        return out


class MandelbrotMode(EffectMode):
    mode_id = "mandelbrot"
    field_class = MandelbrotField
    tick_interval = 0.05
