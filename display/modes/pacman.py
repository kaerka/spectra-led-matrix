"""Attract-mode Pac-Man — maze dots, simple ghost scatter/chase, auto reset."""

from __future__ import annotations

from collections import deque

import numpy as np

from display.modes.effect_base import EffectField, EffectMode

_STEP_S = (0.16, 0.10, 0.065, 0.04)
_DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))
_MODE_S = 6.0

# Symmetric maze templates (# wall, . dot); width must be odd-ish for symmetry.
_MAZES = (
    [
        "###############",
        "#.............#",
        "#.###.###.###.#",
        "#.............#",
        "#.###.###.###.#",
        "#.....#.......#",
        "#.....#.......#",
        "#.###.###.###.#",
        "#.............#",
        "#.....#.......#",
        "#.###.###.###.#",
        "#.............#",
        "#.###.###.###.#",
        "#.............#",
        "###############",
    ],
    [
        "#############",
        "#...........#",
        "#.##.###.##.#",
        "#...........#",
        "###.#.#.#.###",
        "#...#...#...#",
        "#.####.####.#",
        "#...........#",
        "#.##.###.##.#",
        "#...........#",
        "#############",
    ],
)


def _pick_maze(cols_target: int) -> list[str]:
    best = _MAZES[0]
    for m in _MAZES:
        if abs(len(m[0]) - cols_target) < abs(len(best[0]) - cols_target):
            best = m
    return best


class PacmanField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        self.step_s = _STEP_S[values["speed"]]
        short = min(width, height)
        target = 15 if short < 80 else (21 if short < 128 else 27)
        template = _pick_maze(target)
        self.cols = len(template[0])
        self.rows = len(template)
        self.cell = max(1, min(width // (self.cols + 2), height // (self.rows + 2)))
        bw, bh = self.cols * self.cell, self.rows * self.cell
        self.x_off = (width - bw) // 2
        self.y_off = (height - bh) // 2
        gain = settings.gain
        self.pac_rgb = np.asarray(settings.stops[0], dtype=np.float32) * gain
        self.ghost_rgbs = [
            np.asarray(settings.stops[i % len(settings.stops)], dtype=np.float32) * gain
            for i in range(1, 5)
        ]
        wall_base = np.asarray(settings.stops[0], dtype=np.float32) * gain * 0.22
        if wall_base.sum() < 12:
            wall_base = np.array([48, 48, 48], dtype=np.float32) * gain
        self.wall_rgb = wall_base
        self.dot_rgb = self.pac_rgb * 0.35
        self.n_ghosts = 4 if self.cols >= 21 else (3 if self.cols >= 17 else 2)
        self._accum = 0.0
        self._mode_t = 0.0
        self._chase = False
        self._load_maze(template)
        self._reset_actors()

    def _load_maze(self, template: list[str]) -> None:
        self.walls = np.zeros((self.rows, self.cols), dtype=bool)
        self.dots = np.zeros((self.rows, self.cols), dtype=bool)
        for y, row in enumerate(template):
            for x, ch in enumerate(row):
                if ch == "#":
                    self.walls[y, x] = True
                elif ch in ". ":
                    if ch == ".":
                        self.dots[y, x] = True

    def _reset_actors(self) -> None:
        free = [(x, y) for y in range(self.rows) for x in range(self.cols) if self.dots[y, x]]
        if not free:
            for y in range(self.rows):
                for x in range(self.cols):
                    if not self.walls[y, x]:
                        self.dots[y, x] = True
            free = [(x, y) for y in range(self.rows) for x in range(self.cols) if self.dots[y, x]]
        self.pac = free[len(free) // 2]
        self.pac_dir = (1, 0)
        self._mode_t = 0.0
        self._chase = False
        corners = [(1, 1), (self.cols - 2, 1), (1, self.rows - 2), (self.cols - 2, self.rows - 2)]
        self.ghosts: list[tuple[int, int, tuple[int, int], tuple[int, int]]] = []
        for i in range(self.n_ghosts):
            gx = self.cols // 2 + (i - 1)
            gy = self.rows // 2
            if self.walls[gy, gx]:
                gx, gy = corners[i % len(corners)]
            self.ghosts.append((gx, gy, corners[i % len(corners)], (1, 0)))

    def _neighbors(self, x: int, y: int):
        for dx, dy in _DIRS:
            nx, ny = x + dx, y + dy
            if 0 <= nx < self.cols and 0 <= ny < self.rows and not self.walls[ny, nx]:
                yield nx, ny, (dx, dy)

    def _bfs(self, start: tuple[int, int], goals: set[tuple[int, int]]) -> tuple[int, int] | None:
        if start in goals:
            return (0, 0)
        q = deque([start])
        prev: dict[tuple[int, int], tuple[tuple[int, int], tuple[int, int]] | None] = {start: None}
        while q:
            cur = q.popleft()
            if cur in goals:
                path_dir = None
                node = cur
                while prev[node] is not None:
                    p, d = prev[node]
                    path_dir = d
                    node = p
                return path_dir if path_dir else (1, 0)
            x, y = cur
            for nx, ny, d in self._neighbors(x, y):
                nxt = (nx, ny)
                if nxt in prev:
                    continue
                prev[nxt] = (cur, d)
                q.append(nxt)
        return None

    def _bfs_to(self, start: tuple[int, int], goal: tuple[int, int]) -> tuple[int, int] | None:
        return self._bfs(start, {goal})

    def _choose_pac_dir(self) -> tuple[int, int]:
        dots = {(x, y) for y in range(self.rows) for x in range(self.cols) if self.dots[y, x]}
        if not dots:
            return self.pac_dir
        d = self._bfs(self.pac, dots)
        if d and (d[0] != -self.pac_dir[0] or d[1] != -self.pac_dir[1]):
            return d
        for dx, dy in (self.pac_dir, * _DIRS):
            nx, ny = self.pac[0] + dx, self.pac[1] + dy
            if 0 <= nx < self.cols and 0 <= ny < self.rows and not self.walls[ny, nx]:
                return dx, dy
        return self.pac_dir

    def _ghost_dir(self, pos: tuple[int, int], target: tuple[int, int], cur_dir: tuple[int, int]) -> tuple[int, int]:
        reverse = (-cur_dir[0], -cur_dir[1])
        best = None
        best_dist = 1e9
        for dx, dy in _DIRS:
            if (dx, dy) == reverse:
                continue
            nx, ny = pos[0] + dx, pos[1] + dy
            if not (0 <= nx < self.cols and 0 <= ny < self.rows) or self.walls[ny, nx]:
                continue
            dist = abs(nx - target[0]) + abs(ny - target[1])
            if dist < best_dist:
                best_dist = dist
                best = (dx, dy)
        return best if best else cur_dir

    def _step(self) -> None:
        if not self.dots.any():
            self._load_maze(_pick_maze(self.cols))
            self._reset_actors()
            return

        self.pac_dir = self._choose_pac_dir()
        nx, ny = self.pac[0] + self.pac_dir[0], self.pac[1] + self.pac_dir[1]
        if not self.walls[ny, nx]:
            self.pac = (nx, ny)
            self.dots[ny, nx] = False

        for i, (gx, gy, scatter, gdir) in enumerate(self.ghosts):
            target = self.pac if self._chase else scatter
            if self._chase and i == 1:
                target = (self.pac[0] + self.pac_dir[0] * 3, self.pac[1] + self.pac_dir[1] * 3)
            ndir = self._ghost_dir((gx, gy), target, gdir)
            ngx, ngy = gx + ndir[0], gy + ndir[1]
            if not self.walls[ngy, ngx]:
                gx, gy = ngx, ngy
                gdir = ndir
            self.ghosts[i] = (gx, gy, scatter, gdir)
            if (gx, gy) == self.pac:
                self._load_maze(_pick_maze(self.cols))
                self._reset_actors()
                return

    def _paint(self) -> np.ndarray:
        grid = np.zeros((self.rows, self.cols, 3), dtype=np.float32)
        grid[self.walls] = self.wall_rgb
        ys, xs = np.where(self.dots)
        for x, y in zip(xs, ys):
            grid[y, x] = self.dot_rgb
        px, py = self.pac
        grid[py, px] = self.pac_rgb
        for i, (gx, gy, _, _) in enumerate(self.ghosts):
            grid[gy, gx] = self.ghost_rgbs[i % len(self.ghost_rgbs)]
        return grid

    def frame(self, t: float, dt: float) -> np.ndarray:
        self._mode_t += dt
        if self._mode_t >= _MODE_S:
            self._mode_t = 0.0
            self._chase = not self._chase
        self._accum += dt
        while self._accum >= self.step_s:
            self._accum -= self.step_s
            self._step()
        grid = self._paint()
        out = np.zeros((self.height, self.width, 3), dtype=np.float32)
        c = self.cell
        big = np.repeat(np.repeat(grid, c, axis=0), c, axis=1)
        h, w = big.shape[:2]
        out[self.y_off:self.y_off + h, self.x_off:self.x_off + w] = big
        return np.clip(out, 0, 255).astype(np.uint8)


class PacmanMode(EffectMode):
    mode_id = "pacman"
    field_class = PacmanField
    tick_interval = 0.03
