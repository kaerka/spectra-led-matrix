"""Lava lamp — metaball wax blobs rising and sinking above a pool, lit from below."""

from __future__ import annotations

import numpy as np
from PIL import Image

from display.modes.effect_base import EffectField, EffectMode

# Rise-and-fall laps per second per speed level (each blob varies ±30%).
_LAPS_PER_SEC = (1 / 60, 1 / 35, 1 / 20, 1 / 10)
_BLOB_COUNT = (4, 6, 9)
_POOL = 0.08          # wax pool depth as a share of the height
_STRETCH = 0.75       # < 1 makes blobs taller than wide
_LEVELS = 320         # field quantisation for the colour LUT
_LEVEL_SCALE = 80.0   # LUT steps per unit of field (edge band 0.9-1.1 gets 16)


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

        # The metaball field is smooth, so it is evaluated on a coarser grid and upsampled.
        self.ds = 2 if short >= 96 else 1
        self.fw, self.fh = -(-width // self.ds), -(-height // self.ds)
        self.fx = (np.arange(self.fw, dtype=np.float32) * self.ds)[None, :]
        self.fy = (np.arange(self.fh, dtype=np.float32) * self.ds)[:, None]
        # Lit from the bottom: brighter towards the base.
        light = (0.45 + 0.55 * np.arange(height, dtype=np.float32) / max(1, height - 1))[:, None, None]
        wax, liquid = (np.asarray(c, dtype=np.float32) for c in self._colors())
        gain = self.settings.gain
        # Colour depends only on (row, field value): one LUT row per scanline.
        levels = np.arange(_LEVELS, dtype=np.float32) / _LEVEL_SCALE
        edge = _smoothstep(0.9, 1.1, levels)[None, :, None]
        core = np.clip((levels - 1.0) / 3.0, 0.0, 1.0)[None, :, None]
        liquid_lit = liquid * light * gain
        wax_lit = wax * (0.7 + 0.3 * light) * gain
        lut = liquid_lit * (1 - edge) + wax_lit * (0.8 + 0.2 * core) * edge
        self.lut = np.clip(lut, 0, 255).astype(np.uint8).reshape(-1, 3)
        self.row_base = (np.arange(height, dtype=np.int32) * _LEVELS)[:, None]

    def _colors(self):
        stops = self.settings.stops
        return stops[0], stops[1 % len(stops)]

    def field(self, t: float, dt: float) -> np.ndarray:
        self.theta += self.omega * dt
        h = self.height
        # cos = 1 at the bottom: blobs leave the pool, rise past the top edge, return.
        by = h * (0.5 + 0.6 * np.cos(self.theta))
        bx = self.x0 + self.sway * np.sin(0.5 * self.theta + self.phase)
        f = np.zeros((self.fh, self.fw), dtype=np.float32)
        for x, y, r in zip(bx, by, self.radius):
            d2 = ((self.fy - y) * _STRETCH) ** 2 + (self.fx - x) ** 2
            f += (r * r) / (d2 + 1.0)
        pool = _POOL * h * (1 + 0.15 * np.sin(self.fx / self.width * 4 * np.pi + t * 0.5))
        f += (pool / np.maximum(1.0, h - self.fy)) ** 2
        if self.ds > 1:
            big = Image.fromarray(f, mode="F").resize((self.fw * self.ds, self.fh * self.ds), Image.BILINEAR)
            f = np.asarray(big)[:h, : self.width]
        return f

    def frame(self, t: float, dt: float) -> np.ndarray:
        f = self.field(t, dt)
        q = np.minimum(f * _LEVEL_SCALE, _LEVELS - 1).astype(np.int32)
        return self.lut[self.row_base + q]


class LavaLampMode(EffectMode):
    mode_id = "lava_lamp"
    field_class = LavaLampField
    tick_interval = 0.04
