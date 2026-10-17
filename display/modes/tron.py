"""Tron light cycles — AI bikes leave walls until they crash; then reset."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from display.modes.effect_base import EffectField, EffectMode
from display.modes.effect_config import sample_cyclic

_STEP_S = (0.14, 0.08, 0.045, 0.025)
_DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))
_PAUSE_S = 1.4


@dataclass
class _Bike:
    x: int
    y: int
    dx: int
    dy: int
    alive: bool = True
    rgb: tuple[int, int, int] = (255, 140, 20)


class TronField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        self.n_bikes = 2 + values["bikes"]  # 0→2 … 3→5
        self.step_s = _STEP_S[values["speed"]]
        # Logical grid: 1 cell ≈ 1–2 panel pixels so trails read on mini and walls.
        short = min(width, height)
        self.cell = 2 if short >= 96 else 1
        self.cols = width // self.cell
        self.rows = height // self.cell
        self.x_off = (width - self.cols * self.cell) // 2
        self.y_off = (height - self.rows * self.cell) // 2
        colors = sample_cyclic(settings.stops, 5)
        self.bike_rgbs = [
            tuple(int(min(255, c * settings.gain)) for c in colors[i])
            for i in range(5)
        ]
        wall = np.asarray(settings.stops[0], dtype=np.float32) * settings.gain * 0.35
        self.border_rgb = tuple(int(min(255, c)) for c in wall)
        self._accum = 0.0
        self._pause = 0.0
        self._reset()

    def _reset(self) -> None:
        self.trail = np.zeros((self.rows, self.cols), dtype=np.int8)  # 0 empty, >0 bike id
        # Soft arena border (impassable).
        self.trail[0, :] = -1
        self.trail[-1, :] = -1
        self.trail[:, 0] = -1
        self.trail[:, -1] = -1
        self.bikes = self._spawn()
        for i, b in enumerate(self.bikes):
            self.trail[b.y, b.x] = i + 1
        self._pause = 0.0

    def _spawn(self) -> list[_Bike]:
        """Start near edges, aimed inward — classic light-cycle face-off."""
        cx, cy = self.cols // 2, self.rows // 2
        margin = max(3, min(self.cols, self.rows) // 8)
        # Left, right, top, bottom, then a fifth offset on the left edge.
        slots = [
            (margin, cy, 1, 0),
            (self.cols - 1 - margin, cy, -1, 0),
            (cx, margin, 0, 1),
            (cx, self.rows - 1 - margin, 0, -1),
            (margin, max(margin + 2, cy - max(4, self.rows // 6)), 1, 0),
        ]
        return [
            _Bike(x=x, y=y, dx=dx, dy=dy, rgb=self.bike_rgbs[i])
            for i, (x, y, dx, dy) in enumerate(slots[: self.n_bikes])
        ]

    def _open_score(self, x: int, y: int, blocked) -> int:
        """Bounded flood-fill: how much room is ahead (prefer open space)."""
        if (x, y) in blocked or not (0 <= x < self.cols and 0 <= y < self.rows):
            return 0
        if self.trail[y, x] != 0:
            return 0
        seen = {(x, y)}
        q = deque([(x, y)])
        limit = 48
        while q and len(seen) < limit:
            cx, cy = q.popleft()
            for dx, dy in _DIRS:
                nx, ny = cx + dx, cy + dy
                if (nx, ny) in seen or (nx, ny) in blocked:
                    continue
                if not (0 <= nx < self.cols and 0 <= ny < self.rows):
                    continue
                if self.trail[ny, nx] != 0:
                    continue
                seen.add((nx, ny))
                q.append((nx, ny))
        return len(seen)

    def _choose_dir(self, bike: _Bike, others_next: set[tuple[int, int]]) -> tuple[int, int]:
        # Prefer continuing; never reverse in place.
        reverse = (-bike.dx, -bike.dy)
        candidates = []
        for dx, dy in _DIRS:
            if (dx, dy) == reverse:
                continue
            nx, ny = bike.x + dx, bike.y + dy
            if not (0 <= nx < self.cols and 0 <= ny < self.rows):
                continue
            if self.trail[ny, nx] != 0:
                continue
            if (nx, ny) in others_next:
                continue
            score = self._open_score(nx, ny, others_next)
            # Slight bias to keep current heading when scores are close.
            if (dx, dy) == (bike.dx, bike.dy):
                score += 3
            candidates.append((score, dx, dy))
        if not candidates:
            return bike.dx, bike.dy  # crash next step
        candidates.sort(reverse=True)
        best = candidates[0][0]
        top = [(dx, dy) for s, dx, dy in candidates if s >= best - 2]
        pick = top[int(self.rng.integers(0, len(top)))]
        return pick

    def _step(self) -> None:
        alive = [b for b in self.bikes if b.alive]
        if len(alive) <= 1:
            self._pause = _PAUSE_S
            return
        # Tentative next cells for collision avoidance between bikes.
        planned: list[tuple[_Bike, int, int, int, int]] = []
        reserved: set[tuple[int, int]] = set()
        for b in alive:
            dx, dy = self._choose_dir(b, reserved)
            nx, ny = b.x + dx, b.y + dy
            planned.append((b, nx, ny, dx, dy))
            reserved.add((nx, ny))
        # Resolve: wall/trail/head-on.
        claimed: dict[tuple[int, int], _Bike] = {}
        for b, nx, ny, dx, dy in planned:
            b.dx, b.dy = dx, dy
            if not (0 <= nx < self.cols and 0 <= ny < self.rows) or self.trail[ny, nx] != 0:
                b.alive = False
                continue
            if (nx, ny) in claimed:
                # Head-on / same cell — both out.
                claimed[(nx, ny)].alive = False
                b.alive = False
                continue
            claimed[(nx, ny)] = b
        for (nx, ny), b in claimed.items():
            if not b.alive:
                continue
            b.x, b.y = nx, ny
            self.trail[ny, nx] = self.bikes.index(b) + 1
        if sum(1 for b in self.bikes if b.alive) <= 1:
            self._pause = _PAUSE_S

    def frame(self, t: float, dt: float) -> np.ndarray:
        if self._pause > 0:
            self._pause -= dt
            if self._pause <= 0:
                self._reset()
        else:
            self._accum += dt
            while self._accum >= self.step_s and self._pause <= 0:
                self._accum -= self.step_s
                self._step()
                if self._pause > 0:
                    self._accum = 0
                    break
        # Paint logical grid colours, then nearest-neighbour scale to the panel.
        grid = np.zeros((self.rows, self.cols, 3), dtype=np.float32)
        border = np.asarray(self.border_rgb, dtype=np.float32)
        grid[self.trail < 0] = border
        for i, rgb in enumerate(self.bike_rgbs):
            mask = self.trail == (i + 1)
            if mask.any():
                grid[mask] = np.asarray(rgb, dtype=np.float32) * 0.75
        for b in self.bikes:
            if b.alive:
                grid[b.y, b.x] = b.rgb
        if self.cell == 1 and self.x_off == 0 and self.y_off == 0 \
                and self.cols == self.width and self.rows == self.height:
            return np.clip(grid, 0, 255).astype(np.uint8)
        out = np.zeros((self.height, self.width, 3), dtype=np.float32)
        c = self.cell
        # Repeat each cell into a c×c block.
        big = np.repeat(np.repeat(grid, c, axis=0), c, axis=1)
        h, w = big.shape[:2]
        out[self.y_off:self.y_off + h, self.x_off:self.x_off + w] = big
        return np.clip(out, 0, 255).astype(np.uint8)


class TronMode(EffectMode):
    mode_id = "tron"
    field_class = TronField
    tick_interval = 0.03
