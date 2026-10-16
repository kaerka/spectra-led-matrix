"""Lava lamp — metaball wax blobs rising and sinking above a pool, lit from below."""

from __future__ import annotations

import numpy as np

from display.modes.effect_base import EffectField, EffectMode

# Rise-and-fall laps per second per speed level (each blob varies ±30%).
_LAPS_PER_SEC = (1 / 60, 1 / 35, 1 / 20, 1 / 10)
_BLOB_COUNT = (4, 6, 9)
_POOL = 0.08          # wax pool depth as a share of the height
_STRETCH = 0.75       # < 1 makes blobs taller than wide


def _smoothstep(lo: float, hi: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3 - 2 * t)


class LavaLampField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        n = _BLOB_COUNT[values["blobs"]]
        short = min(width, height)
        rng = self.rng
        self.x0 = rng.uniform(0.15, 0.85, n) * width
        self.sway = rng.uniform(0.03, 0.08, n) * width
        self.radius = rng.uniform(0.05, 0.10, n) * short
        self.theta = rng.uniform(0, 2 * np.pi, n)
        self.omega = 2 * np.pi * _LAPS_PER_SEC[values["speed"]] * rng.uniform(0.7, 1.3, n)
        self.phase = rng.uniform(0, 2 * np.pi, n)

        self.ys, self.xs = np.mgrid[0:height, 0:width].astype(np.float32)
        # Lit from the bottom: brighter towards the base.
        light = 0.45 + 0.55 * (self.ys / max(1, height - 1))
        wax, liquid = (np.asarray(c, dtype=np.float32) for c in self._colors())
        self.liquid = liquid * light[..., None]
        self.wax = wax * (0.7 + 0.3 * light)[..., None]

    def _colors(self):
        stops = self.settings.stops
        return stops[0], stops[1 % len(stops)]

    def field(self, t: float, dt: float) -> np.ndarray:
        self.theta += self.omega * dt
        h = self.height
        # cos = 1 at the bottom: blobs leave the pool, rise past the top edge, return.
        by = h * (0.5 + 0.6 * np.cos(self.theta))
        bx = self.x0 + self.sway * np.sin(0.5 * self.theta + self.phase)
        f = np.zeros((h, self.width), dtype=np.float32)
        for x, y, r in zip(bx, by, self.radius):
            d2 = (self.xs - x) ** 2 + ((self.ys - y) * _STRETCH) ** 2
            f += (r * r) / (d2 + 1.0)
        pool = _POOL * h * (1 + 0.15 * np.sin(self.xs / self.width * 4 * np.pi + t * 0.5))
        f += (pool / np.maximum(1.0, h - self.ys)) ** 2
        return f

    def frame(self, t: float, dt: float) -> np.ndarray:
        f = self.field(t, dt)
        edge = _smoothstep(0.9, 1.1, f)[..., None]
        core = np.clip((f - 1.0) / 3.0, 0.0, 1.0)[..., None]
        wax = self.wax * (0.8 + 0.2 * core)
        rgb = (self.liquid * (1 - edge) + wax * edge) * self.settings.gain
        return np.clip(rgb, 0, 255).astype(np.uint8)


class LavaLampMode(EffectMode):
    mode_id = "lava_lamp"
    field_class = LavaLampField
    tick_interval = 0.04
