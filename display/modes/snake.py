"""Self-playing Snake — BFS toward food, restart on win or death."""

from __future__ import annotations

from collections import deque

import numpy as np

from display.modes.effect_base import EffectField, EffectMode

_STEP_S = (0.22, 0.12, 0.07, 0.04)
_CELL = (4, 6, 10)  # Fine / Medium / Coarse at 64 px; scales with short side


def _grid_size(short: int, grid: int) -> int:
    cell = max(2, round(_CELL[grid] * short / 64))
    return max(6, short // cell)


class SnakeField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        short = min(width, height)
        self.cols = self.rows = _grid_size(short, values["grid"])
        self.cell = min(width // self.cols, height // self.rows)
        self.x_off = (width - self.cols * self.cell) // 2
        self.y_off = (height - self.rows * self.cell) // 2
        self.step_s = _STEP_S[values["speed"]]
        self.snake_rgb = np.asarray(settings.stops[0], dtype=np.float32) * settings.gain
        self.food_rgb = np.asarray(settings.stops[1 % len(settings.stops)], dtype=np.float32) * settings.gain
        self._accum = 0.0
        self._reset()

    def _reset(self) -> None:
        mid = self.cols // 2
        self.body = deque([(mid - 1, mid), (mid, mid), (mid + 1, mid)])
        self.dir = (1, 0)
        self._place_food()
        self.alive = True
        self.won = False

    def _place_food(self) -> None:
        occupied = set(self.body)
        free = [(x, y) for y in range(self.rows) for x in range(self.cols) if (x, y) not in occupied]
        if not free:
            self.won = True
            self.food = None
            return
        self.food = free[int(self.rng.integers(0, len(free)))]

    def _neighbors(self, x: int, y: int):
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < self.cols and 0 <= ny < self.rows:
                yield nx, ny, (dx, dy)

    def _bfs(self, start, goal, blocked) -> list | None:
        q = deque([start])
        prev = {start: None}
        while q:
            cur = q.popleft()
            if cur == goal:
                path = []
                while cur is not None:
                    path.append(cur)
                    cur = prev[cur]
                path.reverse()
                return path
            x, y = cur
            for nx, ny, _d in self._neighbors(x, y):
                nxt = (nx, ny)
                if nxt in prev or nxt in blocked:
                    continue
                prev[nxt] = cur
                q.append(nxt)
        return None

    def _choose_dir(self) -> tuple[int, int]:
        head = self.body[-1]
        # Body except tail (tail will vacate unless we grow).
        blocked = set(list(self.body)[:-1])
        path = self._bfs(head, self.food, blocked) if self.food else None
        if path and len(path) >= 2:
            nx, ny = path[1]
            return nx - head[0], ny - head[1]
        # No path to food: take any safe step (prefer continuing).
        prefs = [self.dir, (self.dir[1], -self.dir[0]), (-self.dir[1], self.dir[0]), (-self.dir[0], -self.dir[1])]
        for dx, dy in prefs:
            nx, ny = head[0] + dx, head[1] + dy
            if 0 <= nx < self.cols and 0 <= ny < self.rows and (nx, ny) not in blocked:
                return dx, dy
        return self.dir

    def _step(self) -> None:
        if not self.alive or self.won:
            self._reset()
            return
        self.dir = self._choose_dir()
        hx, hy = self.body[-1]
        nx, ny = hx + self.dir[0], hy + self.dir[1]
        if not (0 <= nx < self.cols and 0 <= ny < self.rows) or (nx, ny) in set(list(self.body)[:-1]):
            self.alive = False
            return
        self.body.append((nx, ny))
        if self.food and (nx, ny) == self.food:
            self._place_food()
            if self.won:
                return
        else:
            self.body.popleft()

    def frame(self, t: float, dt: float) -> np.ndarray:
        self._accum += dt
        while self._accum >= self.step_s:
            self._accum -= self.step_s
            self._step()
            if not self.alive or self.won:
                self._accum = 0
                break
        out = np.zeros((self.height, self.width, 3), dtype=np.float32)
        c = self.cell
        for i, (x, y) in enumerate(self.body):
            # Head slightly brighter.
            mul = 1.0 if i == len(self.body) - 1 else 0.75
            y0, x0 = self.y_off + y * c, self.x_off + x * c
            out[y0:y0 + c - 1, x0:x0 + c - 1] = self.snake_rgb * mul
        if self.food:
            fx, fy = self.food
            y0, x0 = self.y_off + fy * c, self.x_off + fx * c
            out[y0:y0 + c - 1, x0:x0 + c - 1] = self.food_rgb
        return np.clip(out, 0, 255).astype(np.uint8)


class SnakeMode(EffectMode):
    mode_id = "snake"
    field_class = SnakeField
    tick_interval = 0.03
