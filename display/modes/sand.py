"""Falling sand cellular sim or rain streaks on glass with drips."""

from __future__ import annotations

import numpy as np

from display.modes.effect_base import EffectField, EffectMode

_SPAWN_PER_S = (2.0, 6.0, 14.0, 28.0)
_UPDATES_MULT = (1.0, 1.6, 2.4, 3.5)
_RAIN_DROPS = (8, 18, 35, 60)


class SandField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        self.rain_mode = values["style"] == 1
        short = min(width, height)
        self.cell = 2 if short >= 96 else 1
        self.cols = width // self.cell
        self.rows = height // self.cell
        self.x_off = (width - self.cols * self.cell) // 2
        self.y_off = (height - self.rows * self.cell) // 2
        rate = values["rate"]
        self.spawn_rate = _SPAWN_PER_S[rate]
        self.updates = max(1, int(self.rows * _UPDATES_MULT[rate] * 0.15))
        self.particle_rgb = np.asarray(settings.stops[0], dtype=np.float32) * settings.gain
        self.bg_rgb = np.asarray(settings.stops[1 % len(settings.stops)], dtype=np.float32) * settings.gain
        self._spawn_accum = 0.0
        if self.rain_mode:
            self._glass = np.zeros((height, width), dtype=np.float32)
            self._drops = self._init_rain_drops(rate)
        else:
            self.grid = np.zeros((self.rows, self.cols), dtype=np.uint8)

    def _init_rain_drops(self, rate: int) -> list[dict]:
        n = _RAIN_DROPS[rate]
        drops = []
        for _ in range(n):
            drops.append({
                "x": float(self.rng.uniform(0, self.width)),
                "y": float(self.rng.uniform(-self.height, self.height)),
                "vy": float(self.rng.uniform(80, 160)),
                "len": float(self.rng.uniform(4, 12)),
            })
        return drops

    def _spawn_sand(self, n: int) -> None:
        for _ in range(n):
            x = int(self.rng.integers(0, self.cols))
            if self.grid[0, x] == 0:
                self.grid[0, x] = 1

    def _step_sand(self) -> None:
        """Bottom-up pass on occupied cells only."""
        g = self.grid
        ys, xs = np.nonzero(g)
        if ys.size == 0:
            return
        order = np.argsort(-ys)
        for idx in order:
            y, x = int(ys[idx]), int(xs[idx])
            if g[y, x] == 0:
                continue
            if y >= self.rows - 1:
                continue
            if g[y + 1, x] == 0:
                g[y + 1, x] = 1
                g[y, x] = 0
            else:
                dx = int(self.rng.integers(-1, 2))
                nx = x + dx
                if 0 <= nx < self.cols and g[y + 1, nx] == 0:
                    g[y + 1, nx] = 1
                    g[y, x] = 0

    def _step_rain(self, dt: float) -> None:
        self._glass *= max(0.0, 1.0 - 2.5 * dt)
        for d in self._drops:
            d["y"] += d["vy"] * dt
            x, y = int(d["x"]), int(d["y"])
            if y >= self.height + 4:
                d["y"] = float(self.rng.uniform(-20, -4))
                d["x"] = float(self.rng.uniform(0, self.width))
                if self.rng.random() < 0.15:
                    self._add_drip(d["x"])
            ln = int(d["len"])
            for i in range(ln):
                yy = y - i
                if 0 <= yy < self.height and 0 <= x < self.width:
                    self._glass[yy, x] = np.maximum(self._glass[yy, x], 0.85 - i * 0.08)
        # Drips slide down the glass.
        for _ in range(2):
            g = self._glass
            drip = g * 0.98
            drip[1:] = np.maximum(drip[1:], g[:-1] * 0.92)
            self._glass = drip

    def _add_drip(self, x: float) -> None:
        col = int(np.clip(x, 0, self.width - 1))
        h = int(self.rng.integers(3, min(12, self.height // 4)))
        y0 = int(self.rng.integers(0, max(1, self.height - h)))
        self._glass[y0:y0 + h, col] = np.maximum(self._glass[y0:y0 + h, col], 0.95)

    def _blit_grid(self) -> np.ndarray:
        out = np.broadcast_to(self.bg_rgb, (self.height, self.width, 3)).copy()
        if not self.grid.any():
            return out
        c = self.cell
        small = np.where(self.grid[..., None], self.particle_rgb, self.bg_rgb).astype(np.float32)
        big = np.repeat(np.repeat(small, c, axis=0), c, axis=1)
        h, w = big.shape[:2]
        out[self.y_off:self.y_off + h, self.x_off:self.x_off + w] = big
        return out

    def frame(self, t: float, dt: float) -> np.ndarray:
        if self.rain_mode:
            self._step_rain(dt)
            out = np.broadcast_to(self.bg_rgb, (self.height, self.width, 3)).copy()
            trail = self._glass[..., None] * self.particle_rgb
            out = np.clip(out * (1 - self._glass[..., None] * 0.3) + trail, 0, 255)
            return out.astype(np.uint8)
        self._spawn_accum += self.spawn_rate * dt
        while self._spawn_accum >= 1.0:
            self._spawn_accum -= 1.0
            self._spawn_sand(1)
        for _ in range(self.updates):
            self._step_sand()
        return np.clip(self._blit_grid(), 0, 255).astype(np.uint8)


class SandMode(EffectMode):
    mode_id = "sand"
    field_class = SandField
    tick_interval = 0.033
