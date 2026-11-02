"""Falling sand (layered sand-art pours that drain and refill) or rain with splashes."""

from __future__ import annotations

import colorsys
import math

import numpy as np

from display.modes.effect_base import EffectField, EffectMode

_POUR_PER_S = (40.0, 90.0, 180.0, 320.0)  # grains per second at 64 px (scaled by area)
_SAND_STEPS = (2, 3, 4, 5)
_SHADES = 32
_LAYERS = 16
_LAYER_S = 4.0
_FULL = 0.62  # drain once this share of the canvas is sand
_DRAIN_S = 6.0
_RAIN_RATE = (25, 60, 120, 220)  # drops per second at 64 px wide


class SandField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        self.rain_mode = values["style"] == 1
        rate = values["rate"]
        gain = settings.gain
        self.particle = np.asarray(settings.stops[0], dtype=np.float32)
        self.bg = np.asarray(settings.stops[1 % len(settings.stops)], dtype=np.float32) * gain
        self.gain = gain
        self.scale = min(width, height) / 64.0
        if self.rain_mode:
            self.rate = _RAIN_RATE[rate] * width / 64.0
            self.drops = np.zeros((0, 5), dtype=np.float32)  # x, y, vx, vy, len
            self.splash = np.zeros((0, 5), dtype=np.float32)  # x, y, vx, vy, life
            self.buf = np.zeros((height, width, 3), dtype=np.float32)
            self.flash = 0.0
            self.storm = rate == 3
            self._acc = 0.0
        else:
            self.rate = _POUR_PER_S[rate] * (width * height) / 4096.0
            self.steps = _SAND_STEPS[rate]
            # 0 empty, else 1 + layer * _SHADES + shade
            self.grid = np.zeros((height, width), dtype=np.uint16)
            self.lut = np.zeros((1 + _LAYERS * _SHADES, 3), dtype=np.float32)
            self.lut[0] = self.bg
            self._layer = 0
            self._set_layer_colors(0.0)
            self.nozzles = [float(self.rng.uniform(0.2, 0.8)) for _ in range(2 if width >= 96 else 1)]
            self.drain_t = 0.0
            self._acc = 0.0
            self._layer_t = 0.0

    # -------------------------------------------------------------- sand

    def _set_layer_colors(self, hue_offset: float) -> None:
        h, s, v = colorsys.rgb_to_hsv(*(self.particle / 255.0))
        hue = (h + hue_offset) % 1.0
        layer_v = float(self.rng.uniform(0.75, 1.0))
        shade = np.linspace(0.6, 1.1, _SHADES)
        base = 1 + self._layer * _SHADES
        for i in range(_SHADES):
            sat = min(1.0, s * (0.8 + 0.2 * (i % 3)))
            r, g, b = colorsys.hsv_to_rgb(hue, sat, min(1.0, v * layer_v * shade[i]))
            self.lut[base + i] = np.array([r, g, b]) * 255 * self.gain

    def _pour(self, dt: float) -> None:
        self._acc += self.rate * dt
        n = int(self._acc)
        self._acc -= n
        if n <= 0:
            return
        w = self.width
        spread = max(1.0, 1.2 * self.scale)
        for k, pos in enumerate(self.nozzles):
            pos += math.sin(self._layer_t * (0.23 + 0.11 * k) + k * 2.0) * 0.004
            self.nozzles[k] = min(0.85, max(0.15, pos))
        m = len(self.nozzles)
        which = self.rng.integers(m, size=n)
        xs = np.asarray(self.nozzles)[which] * w + self.rng.normal(0, spread, n)
        xs = np.clip(xs.astype(np.int32), 0, w - 1)
        ys = self.rng.integers(0, max(1, int(2 * self.scale)), n)
        empty = self.grid[ys, xs] == 0
        shade = (1 + self._layer * _SHADES + self.rng.integers(0, _SHADES, n)).astype(np.uint16)
        self.grid[ys[empty], xs[empty]] = shade[empty]

    def _step_sand(self, parity: int) -> None:
        g = self.grid
        above, below = g[:-1], g[1:]
        fall = (above != 0) & (below == 0)
        below[fall] = above[fall]
        above[fall] = 0
        d = 1 if parity else -1
        above, below = g[:-1], g[1:]
        if d == 1:
            src, dst = above[:, :-1], below[:, 1:]
        else:
            src, dst = above[:, 1:], below[:, :-1]
        slide = (src != 0) & (dst == 0) & (self.rng.random(src.shape) < 0.85)
        dst[slide] = src[slide]
        src[slide] = 0

    def _frame_sand(self, t: float, dt: float) -> np.ndarray:
        self._layer_t += dt
        if self.drain_t > 0:
            self.drain_t -= dt
            self.grid[-1] = 0
            self.grid[-1, self.rng.random(self.width) < 0.5] = 0
            if self.drain_t <= 0 or not self.grid.any():
                self.drain_t = 0.0
                self.grid[:] = 0
        else:
            self._pour(dt)
            if int(self._layer_t / _LAYER_S) != int((self._layer_t - dt) / _LAYER_S):
                self._layer = (self._layer + 1) % _LAYERS
                self._set_layer_colors(float(self.rng.uniform(-0.035, 0.035)))
            if np.count_nonzero(self.grid) > _FULL * self.grid.size:
                self.drain_t = _DRAIN_S
        for k in range(self.steps):
            self._step_sand((k + int(t * 60)) % 2)
        if self.drain_t > 0:
            self.grid[-1] = 0
        return self.lut[self.grid].astype(np.uint8)

    # -------------------------------------------------------------- rain

    def _frame_rain(self, t: float, dt: float) -> np.ndarray:
        w, h = self.width, self.height
        s = self.scale
        self._acc += self.rate * dt
        n = int(self._acc)
        self._acc -= n
        wind = math.sin(t * 0.13) * 0.18
        if n:
            rows = np.zeros((n, 5), dtype=np.float32)
            rows[:, 0] = self.rng.uniform(-0.2 * w, 1.2 * w, n)
            rows[:, 1] = self.rng.uniform(-0.3 * h, 0, n)
            speed = self.rng.uniform(2.2, 3.4, n) * h
            rows[:, 2] = speed * wind
            rows[:, 3] = speed
            rows[:, 4] = self.rng.uniform(0.04, 0.09, n) * h
            self.drops = np.vstack([self.drops, rows])
        d = self.drops
        d[:, 0] += d[:, 2] * dt
        d[:, 1] += d[:, 3] * dt
        ground = h - 1 - self.rng.uniform(0, 3 * s, len(d))
        landed = d[:, 1] >= ground
        if landed.any():
            k = int(landed.sum()) * 3
            src = np.repeat(d[landed], 3, axis=0)
            sp = np.zeros((k, 5), dtype=np.float32)
            sp[:, 0] = src[:, 0]
            sp[:, 1] = h - 2
            sp[:, 2] = self.rng.normal(0, 0.12 * h, k)
            sp[:, 3] = -self.rng.uniform(0.1, 0.35, k) * h
            sp[:, 4] = self.rng.uniform(0.15, 0.35, k)
            self.splash = np.vstack([self.splash, sp])[-2000:]
        self.drops = d[~landed]

        buf = self.buf
        buf *= math.exp(-14.0 * dt)
        color = self.particle * self.gain
        d = self.drops
        if len(d):
            segs = max(3, int(4 * s))
            for k in range(segs):
                f = k / segs
                x = (d[:, 0] - d[:, 2] / d[:, 3] * d[:, 4] * f).astype(np.int32)
                y = (d[:, 1] - d[:, 4] * f).astype(np.int32)
                ok = (x >= 0) & (x < w) & (y >= 0) & (y < h)
                np.maximum.at(buf, (y[ok], x[ok]), color * (1.0 - 0.8 * f))
        sp = self.splash
        if len(sp):
            sp[:, 0] += sp[:, 2] * dt
            sp[:, 1] += sp[:, 3] * dt
            sp[:, 3] += 1.5 * h * dt
            sp[:, 4] -= dt
            self.splash = sp = sp[(sp[:, 4] > 0) & (sp[:, 1] < h)]
            x, y = sp[:, 0].astype(np.int32), sp[:, 1].astype(np.int32)
            ok = (x >= 0) & (x < w) & (y >= 0)
            np.maximum.at(buf, (y[ok], x[ok]), color[None, :] * np.minimum(1.0, sp[ok, 4:5] * 4))

        out = self.bg * np.linspace(0.6, 1.0, h, dtype=np.float32)[:, None, None] + buf
        puddle = max(1, int(2 * s))
        shimmer = 0.5 + 0.5 * np.sin(np.arange(w) * 0.7 / s + t * 3.0)
        out[-puddle:] += (color * 0.25)[None, None, :] * shimmer[None, :, None]
        if self.storm:
            if self.flash <= 0 and self.rng.random() < dt / 9.0:
                self.flash = 0.35
            if self.flash > 0:
                self.flash -= dt
                if int(self.flash * 20) % 3:
                    out = out + 160 * self.gain
        return np.clip(out, 0, 255).astype(np.uint8)

    def frame(self, t: float, dt: float) -> np.ndarray:
        dt = min(dt, 0.1)
        if self.rain_mode:
            return self._frame_rain(t, dt)
        return self._frame_sand(t, dt)


class SandMode(EffectMode):
    mode_id = "sand"
    field_class = SandField
    tick_interval = 0.033
