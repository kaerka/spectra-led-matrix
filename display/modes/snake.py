"""Self-playing Snake — BFS toward food, restart on win or death."""

from __future__ import annotations

from collections import deque

import numpy as np
from PIL import Image, ImageDraw

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

    def _center(self, x: float, y: float) -> tuple[float, float]:
        c = self.cell
        return self.x_off + (x + 0.5) * c - 0.5, self.y_off + (y + 0.5) * c - 0.5

    def frame(self, t: float, dt: float) -> np.ndarray:
        self._accum += dt
        grew = False
        while self._accum >= self.step_s:
            self._accum -= self.step_s
            before = len(self.body)
            self._prev_tail = self.body[0]
            self._step()
            grew = len(self.body) > before
            if not self.alive or self.won:
                self._accum = 0
                break
        img = Image.new("RGB", (self.width, self.height))
        draw = ImageDraw.Draw(img)
        c = self.cell
        if c < 4:
            for i, (x, y) in enumerate(self.body):
                mul = 1.0 if i == len(self.body) - 1 else 0.55 + 0.35 * i / len(self.body)
                x0, y0 = self.x_off + x * c, self.y_off + y * c
                draw.rectangle([x0, y0, x0 + c - 2, y0 + c - 2], fill=tuple(int(v) for v in self.snake_rgb * mul))
            if self.food:
                fx, fy = self.food
                x0, y0 = self.x_off + fx * c, self.y_off + fy * c
                draw.rectangle([x0, y0, x0 + c - 2, y0 + c - 2], fill=tuple(int(v) for v in self.food_rgb))
            return np.asarray(img)

        frac = min(1.0, self._accum / self.step_s) if self.alive else 0.0
        pts = [self._center(x, y) for x, y in self.body]
        if len(pts) >= 2 and self.alive and not self.won:
            hx, hy = pts[-1]
            dx, dy = self.dir
            pts[-1] = (hx, hy)
            pts.append((hx + dx * c * frac, hy + dy * c * frac))
            tail_prev = getattr(self, "_prev_tail", None)
            if not grew and tail_prev is not None:
                (tx, ty), (nx, ny) = pts[0], pts[1]
                pts[0] = (tx + (nx - tx) * frac, ty + (ny - ty) * frac)
        width = max(2, int(round(c * 0.72)))
        n = len(pts) - 1
        for i in range(n):
            mul = 0.45 + 0.55 * (i + 1) / max(1, n)
            color = tuple(int(v) for v in self.snake_rgb * mul)
            (x0, y0), (x1, y1) = pts[i], pts[i + 1]
            draw.line([(x0, y0), (x1, y1)], fill=color, width=width)
            r = width / 2 - 0.5
            draw.ellipse([x1 - r, y1 - r, x1 + r, y1 + r], fill=color)
        hx, hy = pts[-1]
        r = width / 2 + 0.5
        head = tuple(int(v) for v in self.snake_rgb)
        draw.ellipse([hx - r, hy - r, hx + r, hy + r], fill=head)
        if c >= 8:
            dx, dy = self.dir
            px, py = -dy, dx
            for side in (-1, 1):
                ex, ey = hx + dx * r * 0.3 + px * side * r * 0.45, hy + dy * r * 0.3 + py * side * r * 0.45
                er = max(1.0, r * 0.22)
                draw.ellipse([ex - er, ey - er, ex + er, ey + er], fill=(10, 10, 10))
        if self.food:
            fx, fy = self._center(*self.food)
            fr = c * (0.32 + 0.05 * np.sin(t * 6.0))
            draw.ellipse([fx - fr, fy - fr, fx + fr, fy + fr], fill=tuple(int(v) for v in self.food_rgb))
        return np.asarray(img)


class SnakeMode(EffectMode):
    mode_id = "snake"
    field_class = SnakeField
    tick_interval = 0.03
