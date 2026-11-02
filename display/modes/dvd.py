"""Bouncing DVD logo — corner hits flash and shift hue briefly."""

from __future__ import annotations

import numpy as np

from display.modes.effect_base import EffectField, EffectMode

# Block-letter "DVD" bitmap (rows × cols); 1 = logo pixel.
_DVD = np.array(
    [
        [0, 1, 1, 0, 0, 1, 0, 1, 0, 0, 1, 1, 0],
        [1, 0, 0, 1, 0, 1, 0, 1, 0, 1, 0, 0, 1],
        [1, 0, 0, 1, 0, 1, 0, 1, 0, 1, 0, 0, 1],
        [1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1],
        [1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1],
        [1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1],
        [0, 1, 1, 0, 0, 0, 0, 1, 0, 0, 1, 1, 0],
    ],
    dtype=np.uint8,
)

_PX_PER_SEC = (28, 48, 78, 120)
_SCALE = (0.14, 0.22, 0.32)  # share of min(width, height)


def _hsv_shift(rgb: np.ndarray, degrees: float) -> np.ndarray:
    """Rotate hue on float RGB 0–255."""
    r, g, b = rgb / 255.0
    mx, mn = max(r, g, b), min(r, g, b)
    if mx - mn < 1e-5:
        return rgb
    h = 0.0
    d = mx - mn
    if mx == r:
        h = ((g - b) / d) % 6
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    h = (h / 6 + degrees / 360.0) % 1.0
    s = d / mx if mx else 0.0
    v = mx
    i = int(h * 6) % 6
    f = h * 6 - int(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    if i == 0:
        r2, g2, b2 = v, t, p
    elif i == 1:
        r2, g2, b2 = q, v, p
    elif i == 2:
        r2, g2, b2 = p, v, t
    elif i == 3:
        r2, g2, b2 = p, q, v
    elif i == 4:
        r2, g2, b2 = t, p, v
    else:
        r2, g2, b2 = v, p, q
    return np.array([r2, g2, b2], dtype=np.float32) * 255.0


class DvdField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        self.speed = _PX_PER_SEC[values["speed"]] * (min(width, height) / 64.0)
        short = min(width, height)
        target = short * _SCALE[values["size"]]
        self.scale = max(1, int(round(target / _DVD.shape[0])))
        bh, bw = _DVD.shape
        self.lw, self.lh = bw * self.scale, bh * self.scale
        base = np.asarray(settings.stops[0], dtype=np.float32) * settings.gain
        self.base_rgb = base
        self.hue_shift = 0.0
        self.flash = 0.0
        self.x = float(self.rng.uniform(0, max(1, width - self.lw)))
        self.y = float(self.rng.uniform(0, max(1, height - self.lh)))
        ang = self.rng.uniform(0, 2 * np.pi)
        self.vx = float(np.cos(ang) * self.speed)
        self.vy = float(np.sin(ang) * self.speed)

    def frame(self, t: float, dt: float) -> np.ndarray:
        w, h = self.width, self.height
        self.x += self.vx * dt
        self.y += self.vy * dt
        hit_x = hit_y = False
        if self.x <= 0:
            self.x = 0
            self.vx = abs(self.vx)
            hit_x = True
        elif self.x + self.lw >= w:
            self.x = w - self.lw
            self.vx = -abs(self.vx)
            hit_x = True
        if self.y <= 0:
            self.y = 0
            self.vy = abs(self.vy)
            hit_y = True
        elif self.y + self.lh >= h:
            self.y = h - self.lh
            self.vy = -abs(self.vy)
            hit_y = True
        if hit_x and hit_y:
            self.flash = 0.35
            self.hue_shift = (self.hue_shift + 55.0) % 360.0
        elif hit_x or hit_y:
            self.flash = max(self.flash, 0.12)

        self.flash = max(0.0, self.flash - dt)

        rgb = _hsv_shift(self.base_rgb, self.hue_shift)
        if self.flash > 0:
            rgb = np.clip(rgb * (1.0 + 2.5 * self.flash), 0, 255)

        out = np.zeros((h, w, 3), dtype=np.uint8)
        x0, y0 = int(round(self.x)), int(round(self.y))
        for row in range(_DVD.shape[0]):
            if not _DVD[row].any():
                continue
            for col in range(_DVD.shape[1]):
                if not _DVD[row, col]:
                    continue
                sy, sx = y0 + row * self.scale, x0 + col * self.scale
                ey, ex = sy + self.scale, sx + self.scale
                sy, sx = max(0, sy), max(0, sx)
                ey, ex = min(h, ey), min(w, ex)
                if ey > sy and ex > sx:
                    out[sy:ey, sx:ex] = np.clip(rgb, 0, 255).astype(np.uint8)
        return out


class DvdMode(EffectMode):
    mode_id = "dvd"
    field_class = DvdField
    tick_interval = 0.033
