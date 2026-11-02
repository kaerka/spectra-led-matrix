"""Self-playing Tetris — heuristic AI, line clears, soft reset on top-out."""

from __future__ import annotations

import numpy as np

from display.modes.effect_base import EffectField, EffectMode
from display.modes.effect_config import sample_cyclic

_STEP_S = (0.38, 0.22, 0.13, 0.075)
_BOARD_W = 10
_BOARD_H = 20
_FLASH_S = 0.18

# Seven tetrominoes × up to four rotation states (cells in local coords).
_TETROMINOES: tuple[tuple[tuple[tuple[int, int], ...], ...], ...] = (
    (((0, 1), (1, 1), (2, 1), (3, 1)), ((2, 0), (2, 1), (2, 2), (2, 3)), ((0, 2), (1, 2), (2, 2), (3, 2)), ((1, 0), (1, 1), (1, 2), (1, 3))),  # I
    (((0, 0), (0, 1), (1, 1), (2, 1)), ((1, 0), (1, 1), (2, 1), (2, 2)), ((0, 1), (1, 1), (2, 1), (2, 2)), ((0, 0), (0, 1), (1, 0), (1, 1))),  # J
    (((2, 0), (0, 1), (1, 1), (2, 1)), ((1, 0), (1, 1), (1, 2), (2, 2)), ((0, 1), (1, 1), (2, 1), (0, 2)), ((0, 0), (1, 0), (1, 1), (1, 2))),  # L
    (((1, 0), (2, 0), (1, 1), (2, 1)),),  # O
    (((1, 0), (2, 0), (0, 1), (1, 1)), ((0, 0), (0, 1), (1, 1), (2, 1)), ((1, 0), (2, 0), (1, 1), (2, 1)), ((0, 0), (1, 0), (1, 1), (2, 1))),  # S
    (((1, 0), (0, 1), (1, 1), (2, 1)), ((0, 0), (0, 1), (1, 1), (1, 2)), ((0, 1), (1, 1), (2, 1), (2, 2)), ((1, 0), (1, 1), (0, 2), (1, 2))),  # T
    (((0, 0), (1, 0), (1, 1), (2, 1)), ((2, 0), (1, 1), (2, 1), (1, 2)), ((0, 1), (1, 1), (2, 1), (0, 2)), ((0, 0), (0, 1), (1, 1), (1, 2))),  # Z
)


def _rotate_cells(cells: tuple[tuple[int, int], ...]) -> tuple[tuple[int, int], ...]:
    return tuple((y, 3 - x) for x, y in cells)


class TetrisField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        self.step_s = _STEP_S[values["speed"]]
        self.cols, self.rows = _BOARD_W, _BOARD_H
        self.cell = max(1, min(width // (self.cols + 2), height // (self.rows + 2)))
        bw, bh = self.cols * self.cell, self.rows * self.cell
        self.x_off = (width - bw) // 2
        self.y_off = (height - bh) // 2
        colors = sample_cyclic(settings.stops, 7)
        self.piece_rgb = [
            np.asarray(colors[i], dtype=np.float32) * settings.gain for i in range(7)
        ]
        self.board = np.zeros((self.rows, self.cols), dtype=np.int8)
        self._accum = 0.0
        self._flash = 0.0
        self._piece_idx = 0
        self._rot = 0
        self._px = 3
        self._py = 0
        self._plan_col = 3
        self._plan_rot = 0
        self._spawn()

    def _cells(self, kind: int, rot: int, col: int, row: int) -> list[tuple[int, int]]:
        rots = _TETROMINOES[kind]
        cells = rots[rot % len(rots)]
        return [(col + x, row + y) for x, y in cells]

    def _fits(self, kind: int, rot: int, col: int, row: int) -> bool:
        for x, y in self._cells(kind, rot, col, row):
            if x < 0 or x >= self.cols or y >= self.rows:
                return False
            if y >= 0 and self.board[y, x]:
                return False
        return True

    def _drop_row(self, kind: int, rot: int, col: int) -> int:
        row = 0
        while self._fits(kind, rot, col, row + 1):
            row += 1
        return row

    def _lock(self, kind: int, rot: int, col: int, row: int) -> int:
        for x, y in self._cells(kind, rot, col, row):
            if y >= 0:
                self.board[y, x] = kind + 1
        keep = [row for row in self.board if not row.all()]
        cleared = self.rows - len(keep)
        while len(keep) < self.rows:
            keep.insert(0, np.zeros(self.cols, dtype=np.int8))
        self.board = np.stack(keep)
        if cleared:
            self._flash = _FLASH_S
        return cleared

    def _score_placement(self, kind: int, rot: int, col: int) -> float:
        if not self._fits(kind, rot, col, 0):
            return -1e9
        row = self._drop_row(kind, rot, col)
        tmp = self.board.copy()
        for x, y in self._cells(kind, rot, col, row):
            if y >= 0:
                tmp[y, x] = kind + 1
        lines = 0
        for y in range(self.rows):
            if tmp[y].all():
                lines += 1
        holes = 0
        agg_h = 0
        for x in range(self.cols):
            colv = tmp[:, x]
            filled = np.flatnonzero(colv)
            if filled.size:
                agg_h += self.rows - filled[0]
                seen = False
                for y in range(self.rows):
                    if colv[y]:
                        seen = True
                    elif seen:
                        holes += 1
        return lines * 120.0 - holes * 14.0 - agg_h * 1.2

    def _pick_plan(self) -> None:
        best = -1e9
        best_rot, best_col = 0, 3
        for rot in range(4):
            for col in range(-2, self.cols):
                sc = self._score_placement(self._piece_idx, rot, col)
                if sc > best:
                    best, best_rot, best_col = sc, rot, col
        self._plan_rot = best_rot
        self._plan_col = max(0, min(self.cols - 1, best_col))

    def _spawn(self) -> None:
        self._piece_idx = int(self.rng.integers(0, 7))
        self._rot = 0
        self._px = 3
        self._py = 0
        if not self._fits(self._piece_idx, 0, self._px, 0):
            self.board[:] = 0
            if not self._fits(self._piece_idx, 0, self._px, 0):
                return
        self._pick_plan()

    def _step(self) -> None:
        target_rot = self._plan_rot % len(_TETROMINOES[self._piece_idx])
        if self._rot != target_rot:
            nr = (self._rot + 1) % len(_TETROMINOES[self._piece_idx])
            if self._fits(self._piece_idx, nr, self._px, self._py):
                self._rot = nr
                return
        if self._px < self._plan_col and self._fits(self._piece_idx, self._rot, self._px + 1, self._py):
            self._px += 1
            return
        if self._px > self._plan_col and self._fits(self._piece_idx, self._rot, self._px - 1, self._py):
            self._px -= 1
            return
        if self._fits(self._piece_idx, self._rot, self._px, self._py + 1):
            self._py += 1
            return
        self._lock(self._piece_idx, self._rot, self._px, self._py)
        self._spawn()

    def _paint(self, flash_mul: float) -> np.ndarray:
        grid = np.zeros((self.rows, self.cols, 3), dtype=np.float32)
        for y in range(self.rows):
            for x in range(self.cols):
                v = self.board[y, x]
                if v:
                    grid[y, x] = self.piece_rgb[v - 1]
        for x, y in self._cells(self._piece_idx, self._rot, self._px, self._py):
            if 0 <= y < self.rows and 0 <= x < self.cols:
                grid[y, x] = self.piece_rgb[self._piece_idx]
        if flash_mul > 1.0:
            grid *= flash_mul
        return grid

    def frame(self, t: float, dt: float) -> np.ndarray:
        flash_mul = 1.0
        if self._flash > 0:
            self._flash = max(0.0, self._flash - dt)
            flash_mul = 1.0 + 0.85 * (self._flash / _FLASH_S)
        self._accum += dt
        while self._accum >= self.step_s:
            self._accum -= self.step_s
            self._step()
        grid = self._paint(flash_mul)
        out = np.zeros((self.height, self.width, 3), dtype=np.float32)
        c = self.cell
        big = np.repeat(np.repeat(grid, c, axis=0), c, axis=1)
        h, w = big.shape[:2]
        out[self.y_off:self.y_off + h, self.x_off:self.x_off + w] = big
        return np.clip(out, 0, 255).astype(np.uint8)


class TetrisMode(EffectMode):
    mode_id = "tetris"
    field_class = TetrisField
    tick_interval = 0.03
