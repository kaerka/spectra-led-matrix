"""Falling — stick figure tumbling while cave walls scroll upward."""

from __future__ import annotations

import numpy as np

from display.modes.effect_base import EffectField, EffectMode

_SCROLL_PX_S = (18.0, 32.0, 52.0, 85.0)
# Stick-figure height in px at 64 px short side (scaled).
_FIG_H = (5.0, 7.0, 9.0)
# Simple upright stick figure in normalized coords (x right, y down), center ~ (0, 0).
_FIG_PARTS = (
    ((0.0, -0.45), 0.12),   # head
    ((0.0, -0.15), 0.08),   # torso
    ((-0.22, 0.05), 0.06),  # left arm
    ((0.22, 0.05), 0.06),   # right arm
    ((-0.14, 0.42), 0.06),  # left leg
    ((0.14, 0.42), 0.06),   # right leg
)


def _rotate_pts(pts: np.ndarray, angle: float) -> np.ndarray:
    c, s = np.cos(angle), np.sin(angle)
    rot = np.array([[c, -s], [s, c]], dtype=np.float32)
    return pts @ rot.T


class FallingField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        short = min(width, height)
        self.scroll_rate = _SCROLL_PX_S[values["speed"]] * (short / 64.0)
        mid = _FIG_H[1] * short / 64.0
        self.fig_h = max(5, min(9, round(mid)))
        self.fig_rgb = np.asarray(settings.stops[0], dtype=np.float32) * settings.gain
        self.wall_rgb = np.asarray(settings.stops[1 % len(settings.stops)], dtype=np.float32) * settings.gain
        self.bg_rgb = self.wall_rgb * 0.15
        self._scroll = 0.0
        self._spin = 0.0
        self._spin_rate = self.rng.uniform(2.2, 3.8)
        # Tiling cave profile: jagged inward edges per row.
        period = max(height * 2, 128)
        self._period = period
        self._left = self._make_edge_profile(period, inward=1.0)
        self._right = self._make_edge_profile(period, inward=-1.0)

    def _make_edge_profile(self, period: int, inward: float) -> np.ndarray:
        """Rough rocky edge offset (px) per scanline in the tile."""
        rng = self.rng
        raw = rng.uniform(-1, 1, period).astype(np.float32)
        # Smooth noise into jagged cliffs.
        k = 7
        kernel = np.ones(k, dtype=np.float32) / k
        smooth = np.convolve(raw, kernel, mode="same")
        jagged = smooth + 0.35 * rng.uniform(-1, 1, period).astype(np.float32)
        scale = max(3, self.width // 14)
        return (inward * np.abs(jagged) * scale + scale * 0.6).astype(np.float32)

    def _wall_mask(self, scroll_y: float) -> np.ndarray:
        h, w = self.height, self.width
        yy = (np.arange(h, dtype=np.float32) + scroll_y) % self._period
        yi = yy.astype(int)
        left_in = self._left[yi]
        right_in = self._right[yi]
        xx = np.arange(w, dtype=np.float32)
        left_wall = xx[None, :] <= left_in[:, None]
        right_wall = xx[None, :] >= (w - 1 - right_in[:, None])
        return left_wall | right_wall

    def _draw_figure(self, out: np.ndarray, t: float) -> None:
        cx = self.width * 0.5
        cy = self.height * 0.52
        angle = self._spin
        scale = self.fig_h * 0.5
        rgb = self.fig_rgb
        for (px, py), rad in _FIG_PARTS:
            pt = np.array([[px, py]], dtype=np.float32)
            pt = _rotate_pts(pt, angle) * scale + np.array([cx, cy], dtype=np.float32)
            x, y = int(round(pt[0, 0])), int(round(pt[0, 1]))
            r = max(1, int(round(rad * scale)))
            y0, y1 = max(0, y - r), min(self.height, y + r + 1)
            x0, x1 = max(0, x - r), min(self.width, x + r + 1)
            if y1 <= y0 or x1 <= x0:
                continue
            yy, xx = np.ogrid[y0:y1, x0:x1]
            mask = (xx - x) ** 2 + (yy - y) ** 2 <= r * r
            out[y0:y1, x0:x1][mask] = rgb

    def frame(self, t: float, dt: float) -> np.ndarray:
        self._scroll += self.scroll_rate * dt
        self._spin += self._spin_rate * dt
        out = np.broadcast_to(self.bg_rgb, (self.height, self.width, 3)).copy()
        wall = self._wall_mask(self._scroll)
        out[wall] = self.wall_rgb
        # Darken wall interior slightly for depth.
        hole = ~wall
        if hole.any():
            out[hole] *= 0.35
        self._draw_figure(out, t)
        return np.clip(out, 0, 255).astype(np.uint8)


class FallingMode(EffectMode):
    mode_id = "falling"
    field_class = FallingField
    tick_interval = 0.033
