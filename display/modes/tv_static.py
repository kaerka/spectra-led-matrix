"""TV static — no-signal CRT: noise, scanlines, roll bar, soft vignette."""

from __future__ import annotations

import numpy as np

from display.modes.effect_base import EffectField, EffectMode

# Mean noise level and roll-bar chance per second by option index.
_NOISE = (0.35, 0.55, 0.8)
_ROLL_PER_SEC = (0.0, 0.08, 0.25)


class TvStaticField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        self.noise = _NOISE[values["intensity"]]
        self.roll_rate = _ROLL_PER_SEC[values["roll"]]
        tint = np.asarray(settings.stops[0], dtype=np.float32) * settings.gain
        self.tint = tint
        # Soft vignette: brighter centre, dim edges.
        yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
        cx, cy = (width - 1) / 2, (height - 1) / 2
        r = np.sqrt(((xx - cx) / max(1, cx)) ** 2 + ((yy - cy) / max(1, cy)) ** 2)
        self.vignette = np.clip(1.15 - 0.55 * r, 0.35, 1.0).astype(np.float32)
        self.scan = np.ones((height, 1), dtype=np.float32)
        self.scan[1::2, 0] = 0.55
        self._roll_y = -height
        self._roll_active = False
        self._roll_until = 0.0

    def frame(self, t: float, dt: float) -> np.ndarray:
        if self.roll_rate > 0 and not self._roll_active and self.rng.random() < self.roll_rate * dt:
            self._roll_active = True
            self._roll_y = -self.height // 8
            self._roll_until = t + 0.45
        noise = self.rng.random((self.height, self.width), dtype=np.float32)
        # Slight temporal persistence so it doesn't look like pure hash.
        level = np.clip((noise - (1 - self.noise)) / max(0.05, self.noise), 0, 1)
        level *= self.scan * self.vignette
        if self._roll_active:
            if t > self._roll_until:
                self._roll_active = False
            else:
                self._roll_y += max(2, self.height // 16)
                band = max(2, self.height // 20)
                y0 = int(self._roll_y) % (self.height + band) - band
                y1 = min(self.height, y0 + band)
                y0c = max(0, y0)
                if y1 > y0c:
                    level[y0c:y1] = np.maximum(level[y0c:y1], 0.85)
        rgb = level[..., None] * self.tint
        return np.clip(rgb, 0, 255).astype(np.uint8)


class TvStaticMode(EffectMode):
    mode_id = "tv_static"
    field_class = TvStaticField
    tick_interval = 0.033
