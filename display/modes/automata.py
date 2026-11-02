"""Cellular automata pack: Langton's ants, Brian's Brain, Wireworld circuits, Gray-Scott RD."""

from __future__ import annotations

import numpy as np
from PIL import Image

from display.modes.effect_base import EffectField, EffectMode

_ANT_STEPS = (30, 90, 250, 700)  # per frame, shared by all ants
_CA_STEPS = (1, 1, 2, 3)  # Brian / Wireworld generations per frame
_CA_EVERY = (3, 2, 1, 1)  # ... every N frames
_RD_STEPS = (4, 8, 14, 22)
_RESEED_S = 150.0
# Gray-Scott (feed, kill) regimes that make good moving pictures.
_RD_REGIMES = ((0.0367, 0.0649), (0.030, 0.062), (0.046, 0.063), (0.025, 0.060), (0.039, 0.058))


def _cell_size(short: int, kind: int) -> int:
    if kind == 0:  # Langton
        return 2 if short >= 96 else 1
    if kind == 1:  # Brian
        return 2 if short >= 128 else 1
    if kind == 2:  # Wireworld
        return 3 if short >= 128 else 1
    return 2 if short >= 96 else 1  # RD, bilinear-upsampled


def _neighbours(a: np.ndarray) -> np.ndarray:
    """8-neighbour sum on a torus."""
    p = np.pad(a, 1, mode="wrap")
    return (
        p[:-2, :-2] + p[:-2, 1:-1] + p[:-2, 2:]
        + p[1:-1, :-2] + p[1:-1, 2:]
        + p[2:, :-2] + p[2:, 1:-1] + p[2:, 2:]
    )


class AutomataField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        self.kind = values["kind"]
        self.speed = values["speed"]
        self.cell = _cell_size(min(width, height), self.kind)
        self.cols = max(8, width // self.cell)
        self.rows = max(8, height // self.cell)
        self.x_off = (width - self.cols * self.cell) // 2
        self.y_off = (height - self.rows * self.cell) // 2
        stops = settings.stops
        self.colors = [np.asarray(stops[i % len(stops)], dtype=np.float32) * settings.gain for i in range(4)]
        self._frame_n = 0
        self._age = 0.0
        self._reseed()

    # ------------------------------------------------------------ seeding

    def _reseed(self) -> None:
        c, r = self.cols, self.rows
        rng = self.rng
        self._age = 0.0
        if self.kind == 0:
            self.grid = np.zeros((r, c), dtype=np.uint8)
            n = 1 + int(rng.integers(2, 5))
            self.ants = [
                [int(rng.integers(c // 4, 3 * c // 4)), int(rng.integers(r // 4, 3 * r // 4)), int(rng.integers(4)), i]
                for i in range(n)
            ]
        elif self.kind == 1:
            self.grid = np.zeros((r, c), dtype=np.uint8)
            for _ in range(int(rng.integers(3, 7))):
                cx, cy = int(rng.integers(c)), int(rng.integers(r))
                rad = int(rng.integers(3, max(4, min(c, r) // 6)))
                y0, x0 = max(0, cy - rad), max(0, cx - rad)
                patch = rng.random((min(r, cy + rad) - y0, min(c, cx + rad) - x0)) < 0.35
                self.grid[y0 : y0 + patch.shape[0], x0 : x0 + patch.shape[1]][patch] = 1
        elif self.kind == 2:
            self._seed_wireworld()
        else:
            f, k = _RD_REGIMES[int(rng.integers(len(_RD_REGIMES)))]
            self.f, self.k = f, k
            self.u = np.ones((r, c), dtype=np.float32)
            self.v = np.zeros((r, c), dtype=np.float32)
            for _ in range(int(rng.integers(6, 14))):
                cx, cy = int(rng.integers(c)), int(rng.integers(r))
                rad = max(2, min(c, r) // 20)
                yy, xx = np.ogrid[:r, :c]
                m = (xx - cx) ** 2 + (yy - cy) ** 2 <= rad * rad
                self.u[m] = 0.5
                self.v[m] = 0.25 + rng.random(int(m.sum())) * 0.1

    def _seed_wireworld(self) -> None:
        """Clock loops with circulating electrons, each firing pulses down a spur wire."""
        c, r = self.cols, self.rows
        rng = self.rng
        g = np.zeros((r, c), dtype=np.uint8)
        loops = []
        for _ in range(40):
            if len(loops) >= max(4, (c * r) // 260):
                break
            w = int(rng.integers(6, max(7, c // 3)))
            h = int(rng.integers(5, max(6, r // 3)))
            x0 = int(rng.integers(1, max(2, c - w - 1)))
            y0 = int(rng.integers(1, max(2, r - h - 1)))
            if any(not (x0 + w + 2 < a or a + b + 2 < x0 or y0 + h + 2 < y or y + d + 2 < y0) for a, y, b, d in loops):
                continue
            g[y0, x0 : x0 + w + 1] = 1
            g[y0 + h, x0 : x0 + w + 1] = 1
            g[y0 : y0 + h + 1, x0] = 1
            g[y0 : y0 + h + 1, x0 + w] = 1
            loops.append((x0, y0, w, h))
            k = int(rng.integers(2, w - 1))
            g[y0, x0 + k] = 2
            g[y0, x0 + k - 1] = 3
        for x0, y0, w, h in loops:
            y = y0 + h // 2
            right = rng.random() < 0.5
            x = x0 + w + 1 if right else x0 - 1
            step = 1 if right else -1
            while 0 < x < c - 1 and g[y - 1 : y + 2, x + step].sum() == 0 and g[y - 1 : y + 2, x + 2 * step if 0 <= x + 2 * step < c else x].sum() == 0:
                g[y, x] = 1
                x += step
        self.grid = g

    # --------------------------------------------------------------- steps

    def _step_ants(self, steps: int) -> None:
        g = self.grid
        c, r = self.cols, self.rows
        for _ in range(steps // len(self.ants)):
            for ant in self.ants:
                x, y, d, idx = ant
                if g[y, x]:
                    d = (d + 1) % 4
                    g[y, x] = 0
                else:
                    d = (d + 3) % 4
                    g[y, x] = 1 + idx % 3
                dx, dy = ((0, -1), (1, 0), (0, 1), (-1, 0))[d]
                ant[0], ant[1], ant[2] = (x + dx) % c, (y + dy) % r, d

    def _step_brian(self) -> None:
        g = self.grid
        nbr = _neighbours((g == 1).astype(np.uint8))
        nxt = np.zeros_like(g)
        nxt[(g == 0) & (nbr == 2)] = 1
        nxt[g == 1] = 2
        self.grid = nxt

    def _step_wireworld(self) -> None:
        g = self.grid
        heads = _neighbours((g == 2).astype(np.uint8))
        nxt = g.copy()
        nxt[g == 2] = 3
        nxt[g == 3] = 1
        nxt[(g == 1) & ((heads == 1) | (heads == 2))] = 2
        self.grid = nxt

    def _step_rd(self) -> None:
        u, v = self.u, self.v
        pu = np.pad(u, 1, mode="wrap")
        pv = np.pad(v, 1, mode="wrap")
        lap_u = pu[:-2, 1:-1] + pu[2:, 1:-1] + pu[1:-1, :-2] + pu[1:-1, 2:] - 4 * u
        lap_v = pv[:-2, 1:-1] + pv[2:, 1:-1] + pv[1:-1, :-2] + pv[1:-1, 2:] - 4 * v
        uvv = u * v * v
        u += 0.21 * lap_u - uvv + self.f * (1 - u)
        v += 0.105 * lap_v + uvv - (self.f + self.k) * v
        np.clip(u, 0, 1, out=u)
        np.clip(v, 0, 1, out=v)

    # ------------------------------------------------------------- drawing

    def _rgb(self) -> np.ndarray:
        dead, alive, accent, spark = self.colors[1], self.colors[0], self.colors[2], self.colors[3]
        if self.kind == 3:
            t = np.clip(self.v / 0.45, 0, 1)[..., None]
            rgb = dead * (1 - t) + alive * t
            edge = np.clip((self.v - 0.18) * 6, 0, 1) * np.clip((0.5 - self.u) * 4, 0, 1)
            return rgb * (1 - edge[..., None] * 0.5) + spark * edge[..., None] * 0.5
        if self.kind == 0:
            lut = np.stack([dead, alive, accent, spark])
        elif self.kind == 1:
            lut = np.stack([dead, alive, accent * 0.6, spark])
        else:
            lut = np.stack([dead, accent * 0.45, spark, alive])
        return lut[self.grid]

    def frame(self, t: float, dt: float) -> np.ndarray:
        self._frame_n += 1
        self._age += dt
        k = self.kind
        if k == 0:
            self._step_ants(_ANT_STEPS[self.speed])
        elif k in (1, 2) and self._frame_n % _CA_EVERY[self.speed] == 0:
            for _ in range(_CA_STEPS[self.speed]):
                self._step_brian() if k == 1 else self._step_wireworld()
        elif k == 3:
            for _ in range(_RD_STEPS[self.speed]):
                self._step_rd()

        dead = (k == 1 and not (self.grid == 1).any()) or (k == 3 and self.v.max() < 0.02)
        if dead or self._age > _RESEED_S * (2 if k == 2 else 1):
            self._reseed()

        rgb = np.clip(self._rgb(), 0, 255).astype(np.uint8)
        if k == 0:
            for x, y, _, _ in self.ants:
                rgb[y, x] = np.clip(self.colors[3] * 1.2 + 40, 0, 255).astype(np.uint8)
        c = self.cell
        if c > 1:
            img = Image.fromarray(rgb)
            resample = Image.BILINEAR if k == 3 else Image.NEAREST
            rgb = np.asarray(img.resize((self.cols * c, self.rows * c), resample))
        if rgb.shape[:2] == (self.height, self.width):
            return rgb
        out = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        out[:] = np.clip(self.colors[1], 0, 255).astype(np.uint8)
        h, w = rgb.shape[:2]
        out[self.y_off : self.y_off + h, self.x_off : self.x_off + w] = rgb
        return out


class AutomataMode(EffectMode):
    mode_id = "automata"
    field_class = AutomataField
    tick_interval = 0.04
