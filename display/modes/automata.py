"""Cellular automata pack: Langton, Brian, Wireworld, Gray–Scott RD."""

from __future__ import annotations

import numpy as np

from display.modes.effect_base import EffectField, EffectMode

_STEPS_PER_FRAME = (1, 2, 4, 8)
_STATIC_LIMIT = 120


def _grid_dims(w: int, h: int, kind: int) -> tuple[int, int, int]:
    short = min(w, h)
    if kind == 3:  # RD — smaller for cost.
        cell = max(2, short // 32)
    else:
        cell = 2 if short >= 96 else 1
    cols = max(8, w // cell)
    rows = max(8, h // cell)
    return cell, cols, rows


class AutomataField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        self.kind = values["kind"]
        self.steps = _STEPS_PER_FRAME[values["speed"]]
        self.cell, self.cols, self.rows = _grid_dims(width, height, self.kind)
        self.x_off = (width - self.cols * self.cell) // 2
        self.y_off = (height - self.rows * self.cell) // 2
        stops = settings.stops
        self.colors = [
            np.asarray(stops[i % len(stops)], dtype=np.float32) * settings.gain
            for i in range(4)
        ]
        self._static_count = 0
        self._reseed()

    def _reseed(self) -> None:
        rng = self.rng
        c, r = self.cols, self.rows
        k = self.kind
        if k == 0:
            self.grid = np.zeros((r, c), dtype=np.uint8)
            self.ant_x = c // 2
            self.ant_y = r // 2
            self.ant_dir = 0  # 0=N,1=E,2=S,3=W
            self.grid[self.ant_y, self.ant_x] = 1
        elif k == 1:
            self.grid = (rng.random((r, c)) < 0.18).astype(np.uint8)
        elif k == 2:
            self.grid = np.zeros((r, c), dtype=np.uint8)
            self._seed_wireworld()
        else:
            self.u = np.ones((r, c), dtype=np.float32)
            self.v = np.zeros((r, c), dtype=np.float32)
            cx, cy = c // 2, r // 2
            rad = max(2, min(c, r) // 6)
            yy, xx = np.ogrid[:r, :c]
            mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= rad * rad
            self.u[mask] = 0.5
            self.v[mask] = 0.25 + rng.random(mask.sum()) * 0.1
        self._static_count = 0
        self._prev_hash = None

    def _seed_wireworld(self) -> None:
        g = self.grid
        c, r = self.cols, self.rows
        g[:] = 1  # conductor
        # Simple horizontal wire with electron packet.
        y = r // 2
        x0 = max(2, c // 8)
        x1 = min(c - 3, c * 3 // 4)
        g[y, x0:x1] = 1
        if x1 - x0 > 6:
            g[y, x0 + 2] = 2
            g[y, x0 + 3] = 3
        # Small loop clock.
        ly, lx = max(2, r // 4), max(2, c // 5)
        for i in range(6):
            g[ly, lx + i] = 1
            g[ly + i, lx + 5] = 1
        g[ly + 2, lx + 2] = 2
        g[ly + 2, lx + 3] = 3
        # Clear corners to empty.
        g[0, :] = 0
        g[-1, :] = 0
        g[:, 0] = 0
        g[:, -1] = 0

    def _step_langton(self) -> None:
        x, y = self.ant_x, self.ant_y
        g = self.grid
        if g[y, x]:
            self.ant_dir = (self.ant_dir + 1) % 4
            g[y, x] = 0
        else:
            self.ant_dir = (self.ant_dir + 3) % 4
            g[y, x] = 1
        dx, dy = ((0, -1), (1, 0), (0, 1), (-1, 0))[self.ant_dir]
        self.ant_x = (x + dx) % self.cols
        self.ant_y = (y + dy) % self.rows

    def _step_brian(self) -> None:
        g = self.grid.astype(np.int8)
        firing = (g == 1).astype(np.int8)
        nbr = (
            np.roll(firing, 1, 0) + np.roll(firing, -1, 0)
            + np.roll(firing, 1, 1) + np.roll(firing, -1, 1)
            + np.roll(np.roll(firing, 1, 0), 1, 1) + np.roll(np.roll(firing, 1, 0), -1, 1)
            + np.roll(np.roll(firing, -1, 0), 1, 1) + np.roll(np.roll(firing, -1, 0), -1, 1)
        )
        next_g = np.zeros_like(g)
        next_g[(g == 0) & (nbr == 2)] = 1
        next_g[g == 1] = 2
        next_g[g == 2] = 0
        self.grid = next_g.astype(np.uint8)

    def _step_wireworld(self) -> None:
        g = self.grid.astype(np.int8)
        head = (g == 2).astype(np.int8)
        nbr_heads = (
            np.roll(head, 1, 0) + np.roll(head, -1, 0)
            + np.roll(head, 1, 1) + np.roll(head, -1, 1)
            + np.roll(np.roll(head, 1, 0), 1, 1) + np.roll(np.roll(head, 1, 0), -1, 1)
            + np.roll(np.roll(head, -1, 0), 1, 1) + np.roll(np.roll(head, -1, 0), -1, 1)
        )
        next_g = g.copy()
        next_g[g == 2] = 3
        next_g[g == 3] = 1
        next_g[(g == 1) & ((nbr_heads == 1) | (nbr_heads == 2))] = 2
        self.grid = next_g.astype(np.uint8)

    def _step_rd(self) -> None:
        u, v = self.u, self.v
        Du, Dv, f, k = 0.16, 0.08, 0.035, 0.065
        lap_u = (
            np.roll(u, 1, 0) + np.roll(u, -1, 0)
            + np.roll(u, 1, 1) + np.roll(u, -1, 1) - 4 * u
        )
        lap_v = (
            np.roll(v, 1, 0) + np.roll(v, -1, 0)
            + np.roll(v, 1, 1) + np.roll(v, -1, 1) - 4 * v
        )
        uvv = u * v * v
        du = Du * lap_u - uvv + f * (1 - u)
        dv = Dv * lap_v + uvv - (f + k) * v
        self.u = np.clip(u + du, 0, 1)
        self.v = np.clip(v + dv, 0, 1)

    def _sim_step(self) -> None:
        if self.kind == 0:
            self._step_langton()
        elif self.kind == 1:
            self._step_brian()
        elif self.kind == 2:
            self._step_wireworld()
        else:
            self._step_rd()

    def _state_hash(self) -> int:
        if self.kind == 3:
            return hash((self.u.tobytes(), self.v.tobytes()))
        return hash(self.grid.tobytes())

    def _maybe_reseed(self) -> None:
        h = self._state_hash()
        if h == self._prev_hash:
            self._static_count += 1
        else:
            self._static_count = 0
        self._prev_hash = h
        if self._static_count >= _STATIC_LIMIT:
            self._reseed()

    def _grid_to_rgb(self) -> np.ndarray:
        g = self.grid if self.kind != 3 else None
        grid_rgb = np.zeros((self.rows, self.cols, 3), dtype=np.float32)
        if self.kind == 0:
            grid_rgb[g == 0] = self.colors[1]
            grid_rgb[g == 1] = self.colors[0]
        elif self.kind == 1:
            grid_rgb[g == 0] = self.colors[1]
            grid_rgb[g == 1] = self.colors[0]
            grid_rgb[g == 2] = self.colors[2]
        elif self.kind == 2:
            grid_rgb[g == 0] = self.colors[1]
            grid_rgb[g == 1] = self.colors[0] * 0.55
            grid_rgb[g == 2] = self.colors[2]
            grid_rgb[g == 3] = self.colors[3]
        else:
            t = np.clip(self.v / 0.6, 0, 1)
            grid_rgb = self.colors[1] * (1 - t[..., None]) + self.colors[0] * t[..., None]
            spark = (self.u < 0.35) & (self.v > 0.2)
            grid_rgb[spark] = self.colors[3]
        return grid_rgb

    def frame(self, t: float, dt: float) -> np.ndarray:
        for _ in range(self.steps):
            self._sim_step()
        self._maybe_reseed()
        grid_rgb = self._grid_to_rgb()
        c = self.cell
        big = np.repeat(np.repeat(grid_rgb, c, axis=0), c, axis=1)
        out = np.broadcast_to(self.colors[1], (self.height, self.width, 3)).copy()
        h, w = big.shape[:2]
        out[self.y_off:self.y_off + h, self.x_off:self.x_off + w] = big
        return np.clip(out, 0, 255).astype(np.uint8)


class AutomataMode(EffectMode):
    mode_id = "automata"
    field_class = AutomataField
    tick_interval = 0.04
