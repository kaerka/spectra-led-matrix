"""Bouncing DVD logo — new colour on every bounce, celebration on a corner hit."""

from __future__ import annotations

import colorsys
import math

import numpy as np
from PIL import Image, ImageDraw

from display.modes.effect_base import EffectField, EffectMode

_PX_PER_SEC = (0.22, 0.38, 0.6, 0.95)  # canvas short sides per second
_SIZE = (0.34, 0.46, 0.6)  # logo width as share of the short side
_SS = 4  # supersampling for the logo mask
_CELEBRATE_S = 2.0


def _logo_mask(width_px: int) -> np.ndarray:
    """Anti-aliased italic 'DVD' over a disc, as float alpha (h, w)."""
    W = width_px * _SS
    H = int(W * 0.52)
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    letter_h = H * 0.62
    t = letter_h * 0.2  # stroke

    def letter_d(x0: float, w: float) -> None:
        y0, y1 = 0, letter_h
        r = letter_h / 2
        d.rectangle([x0, y0, x0 + w - r, y1], fill=255)
        d.ellipse([x0 + w - 2 * r, y0, x0 + w, y1], fill=255)
        ri = r - t
        d.rectangle([x0 + t, y0 + t, x0 + w - r, y1 - t], fill=0)
        d.ellipse([x0 + w - r - ri, y0 + t, x0 + w - r + ri, y1 - t], fill=0)
        d.rectangle([x0 + t, y0 + t, x0 + t * 1.6, y1 - t], fill=0)

    def letter_v(x0: float, w: float) -> None:
        y1 = letter_h
        cx = x0 + w / 2
        d.polygon([(x0, 0), (x0 + t * 1.3, 0), (cx, y1 - t * 1.5), (x0 + w - t * 1.3, 0), (x0 + w, 0), (cx + t * 0.4, y1), (cx - t * 0.4, y1)], fill=255)

    dw, vw = W * 0.34, W * 0.29
    letter_d(W * 0.02, dw)
    letter_v(W * 0.02 + dw - t * 0.6, vw)
    letter_d(W * 0.02 + dw + vw - t * 1.2, dw)
    img = img.transform(img.size, Image.AFFINE, (1, 0.22, -H * 0.12, 0, 1, 0), Image.BICUBIC)
    d = ImageDraw.Draw(img)
    dy0, dy1 = letter_h + H * 0.08, H - 1
    d.ellipse([W * 0.06, dy0, W * 0.94, dy1], fill=255)
    hole_h = (dy1 - dy0) * 0.28
    mid = (dy0 + dy1) / 2
    d.ellipse([W * 0.38, mid - hole_h, W * 0.62, mid + hole_h], fill=0)
    small = img.resize((width_px, max(1, H // _SS)), Image.LANCZOS)
    return np.asarray(small, dtype=np.float32) / 255.0


class DvdField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        short = min(width, height)
        self.speed = _PX_PER_SEC[values["speed"]] * short
        self.alpha = _logo_mask(max(12, int(short * _SIZE[values["size"]])))
        self.lh, self.lw = self.alpha.shape
        base = np.asarray(settings.stops[0], dtype=np.float32) / 255.0
        self.hue, self.sat, self.val = colorsys.rgb_to_hsv(*base)
        self.sat = max(self.sat, 0.6)
        self.gain = settings.gain
        self.x = float(self.rng.uniform(0, width - self.lw))
        self.y = float(self.rng.uniform(0, height - self.lh))
        ang = self.rng.uniform(0.5, 1.07) + (np.pi / 2) * int(self.rng.integers(4))
        self.vx = float(math.cos(ang) * self.speed)
        self.vy = float(math.sin(ang) * self.speed)
        self.flash = 0.0
        self.celebrate = 0.0
        self.sparks = np.zeros((0, 6), dtype=np.float32)

    def _rgb(self) -> np.ndarray:
        r, g, b = colorsys.hsv_to_rgb(self.hue % 1.0, self.sat, max(self.val, 0.85))
        return np.array([r, g, b], dtype=np.float32) * 255 * self.gain

    def _corner_burst(self, cx: float, cy: float) -> None:
        n = 60 if min(self.width, self.height) >= 128 else 24
        ang = self.rng.uniform(0, 2 * np.pi, n)
        spd = self.rng.uniform(0.2, 0.6, n) * min(self.width, self.height)
        hue = self.rng.random(n)
        rows = np.zeros((n, 6), dtype=np.float32)
        rows[:, 0], rows[:, 1] = cx, cy
        rows[:, 2], rows[:, 3] = np.cos(ang) * spd, np.sin(ang) * spd
        rows[:, 4] = self.rng.uniform(0.8, 1.6, n)
        rows[:, 5] = hue
        self.sparks = np.vstack([self.sparks, rows])

    def frame(self, t: float, dt: float) -> np.ndarray:
        dt = min(dt, 0.1)
        w, h = self.width, self.height
        self.x += self.vx * dt
        self.y += self.vy * dt
        hit_x = hit_y = False
        if self.x <= 0 or self.x + self.lw >= w:
            self.x = min(max(self.x, 0), w - self.lw)
            self.vx = -self.vx
            hit_x = True
        if self.y <= 0 or self.y + self.lh >= h:
            self.y = min(max(self.y, 0), h - self.lh)
            self.vy = -self.vy
            hit_y = True
        if hit_x or hit_y:
            self.hue += 0.17 + 0.2 * float(self.rng.random())
        if hit_x and hit_y:
            self.celebrate = _CELEBRATE_S
            cx = 0 if self.x <= 0 else w
            cy = 0 if self.y <= 0 else h
            self._corner_burst(cx, cy)

        out = np.zeros((h, w, 3), dtype=np.float32)
        self.celebrate = max(0.0, self.celebrate - dt)
        if self.celebrate > 0:
            self.hue += dt * 1.5
        rgb = self._rgb()
        if self.celebrate > 0 and int(self.celebrate * 8) % 2:
            rgb = np.minimum(255, rgb * 1.4 + 40 * self.gain)
        x0, y0 = int(round(self.x)), int(round(self.y))
        out[y0 : y0 + self.lh, x0 : x0 + self.lw] = self.alpha[..., None] * rgb

        if len(self.sparks):
            s = self.sparks
            s[:, 0] += s[:, 2] * dt
            s[:, 1] += s[:, 3] * dt
            s[:, 3] += 0.4 * h * dt
            s[:, 4] -= dt
            self.sparks = s = s[(s[:, 4] > 0) & (s[:, 1] < h)]
            xi = s[:, 0].astype(np.int32)
            yi = s[:, 1].astype(np.int32)
            ok = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
            for i in np.flatnonzero(ok):
                r, g, b = colorsys.hsv_to_rgb(float(s[i, 5]), 0.8, 1.0)
                life = min(1.0, float(s[i, 4]))
                out[yi[i], xi[i]] = np.array([r, g, b]) * 255 * self.gain * life
        return np.clip(out, 0, 255).astype(np.uint8)


class DvdMode(EffectMode):
    mode_id = "dvd"
    field_class = DvdField
    tick_interval = 0.033
