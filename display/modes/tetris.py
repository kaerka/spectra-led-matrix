"""Self-playing Tetris — heuristic AI, bevelled blocks, next-piece preview, line clears."""

from __future__ import annotations

import numpy as np

from display.modes.effect_base import EffectField, EffectMode
from display.modes.effect_config import sample_cyclic

_STEP_S = (0.38, 0.22, 0.13, 0.075)  # gravity, seconds per row
_MOVE_FRAC = 0.3  # lateral / rotate moves happen this much faster than gravity
_DROP_FRAC = 0.18  # once lined up, soft-drop speed
_BOARD_W = 10
_BOARD_H = 20
_CLEAR_S = 0.35
_TOPOUT_S = 1.2

# Seven tetrominoes x up to four rotation states (cells in local coords).
_TETROMINOES: tuple[tuple[tuple[tuple[int, int], ...], ...], ...] = (
    (((0, 1), (1, 1), (2, 1), (3, 1)), ((2, 0), (2, 1), (2, 2), (2, 3)), ((0, 2), (1, 2), (2, 2), (3, 2)), ((1, 0), (1, 1), (1, 2), (1, 3))),  # I
    (((0, 0), (0, 1), (1, 1), (2, 1)), ((1, 0), (2, 0), (1, 1), (1, 2)), ((0, 1), (1, 1), (2, 1), (2, 2)), ((1, 0), (1, 1), (0, 2), (1, 2))),  # J
    (((2, 0), (0, 1), (1, 1), (2, 1)), ((1, 0), (1, 1), (1, 2), (2, 2)), ((0, 1), (1, 1), (2, 1), (0, 2)), ((0, 0), (1, 0), (1, 1), (1, 2))),  # L
    (((1, 0), (2, 0), (1, 1), (2, 1)),),  # O
    (((1, 0), (2, 0), (0, 1), (1, 1)), ((1, 0), (1, 1), (2, 1), (2, 2))),  # S
    (((1, 0), (0, 1), (1, 1), (2, 1)), ((1, 0), (1, 1), (2, 1), (1, 2)), ((0, 1), (1, 1), (2, 1), (1, 2)), ((1, 0), (0, 1), (1, 1), (1, 2))),  # T
    (((0, 0), (1, 0), (1, 1), (2, 1)), ((2, 0), (1, 1), (2, 1), (1, 2))),  # Z
)


class TetrisField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        self.step_s = _STEP_S[settings.values["speed"]]
        self.cols, self.rows = _BOARD_W, _BOARD_H
        self.cell = max(2, min((width - 2) // (self.cols + 6), (height - 2) // self.rows))
        c = self.cell
        bw, bh = self.cols * c, self.rows * c
        preview_w = 5 * c
        self.x_off = max(1, (width - bw - preview_w) // 2)
        self.y_off = (height - bh) // 2
        self.preview_x = self.x_off + bw + c
        self.preview_y = self.y_off + c
        colors = sample_cyclic(settings.stops, 7)
        gain = settings.gain
        self.piece_rgb = [np.asarray(colors[i], dtype=np.float32) * gain for i in range(7)]
        self.frame_rgb = np.full(3, 90.0, dtype=np.float32) * gain
        self.tiles = [self._tile(rgb) for rgb in self.piece_rgb]
        self.board = np.zeros((self.rows, self.cols), dtype=np.int8)
        self.lines = 0
        self._accum = 0.0
        self._clearing: list[int] = []
        self._clear_t = 0.0
        self._topout_t = 0.0
        self._next = int(self.rng.integers(7))
        self._spawn()

    def _tile(self, rgb: np.ndarray) -> np.ndarray:
        c = self.cell
        tile = np.broadcast_to(rgb, (c, c, 3)).astype(np.float32).copy()
        if c >= 4:
            hi, lo = np.minimum(255, rgb * 1.45 + 25), rgb * 0.55
            tile[0, :] = hi
            tile[:, 0] = hi
            tile[-1, :] = lo
            tile[:, -1] = lo
        elif c == 3:
            tile[0, 0] = np.minimum(255, rgb * 1.45 + 25)
            tile[-1, -1] = rgb * 0.55
        return tile

    # ------------------------------------------------------------- rules

    def _cells(self, kind: int, rot: int, col: int, row: int) -> list[tuple[int, int]]:
        rots = _TETROMINOES[kind]
        return [(col + x, row + y) for x, y in rots[rot % len(rots)]]

    def _fits(self, kind: int, rot: int, col: int, row: int, board=None) -> bool:
        board = self.board if board is None else board
        for x, y in self._cells(kind, rot, col, row):
            if x < 0 or x >= self.cols or y >= self.rows:
                return False
            if y >= 0 and board[y, x]:
                return False
        return True

    def _score_placement(self, kind: int, rot: int, col: int) -> float:
        if not self._fits(kind, rot, col, 0):
            return -1e9
        row = 0
        while self._fits(kind, rot, col, row + 1):
            row += 1
        tmp = self.board.copy()
        for x, y in self._cells(kind, rot, col, row):
            if y < 0:
                return -1e9
            tmp[y, x] = kind + 1
        full = tmp.all(axis=1)
        lines = int(full.sum())
        tmp = tmp[~full]
        filled = tmp != 0
        any_col = filled.any(axis=0)
        tops = np.where(any_col, filled.argmax(axis=0), filled.shape[0])
        heights = filled.shape[0] - tops
        holes = int((np.cumsum(filled, axis=0) > 0).sum() - filled.sum())
        bump = int(np.abs(np.diff(heights)).sum())
        return lines * 76.0 - heights.sum() * 5.1 - holes * 36.0 - bump * 18.4

    def _spawn(self) -> None:
        self._kind, self._next = self._next, int(self.rng.integers(7))
        self._rot, self._px, self._py = 0, 3, -1
        if not self._fits(self._kind, 0, self._px, 0):
            self._topout_t = _TOPOUT_S
            return
        best, self._plan = -1e10, (0, 3)
        for rot in range(len(_TETROMINOES[self._kind])):
            for col in range(-2, self.cols):
                sc = self._score_placement(self._kind, rot, col)
                if sc > best:
                    best, self._plan = sc, (rot, col)
        self._move_t = 0.0

    def _lock(self) -> None:
        for x, y in self._cells(self._kind, self._rot, self._px, self._py):
            if y >= 0:
                self.board[y, x] = self._kind + 1
        self._clearing = [int(r) for r in np.flatnonzero(self.board.all(axis=1))]
        if self._clearing:
            self._clear_t = _CLEAR_S
        else:
            self._spawn()

    def _step(self) -> float:
        """One action; returns the delay until the next one."""
        rot, col = self._plan
        kind = self._kind
        if self._rot != rot and self._fits(kind, rot, self._px, self._py):
            self._rot = rot
            return self.step_s * _MOVE_FRAC
        if self._px != col:
            nx = self._px + (1 if col > self._px else -1)
            if self._fits(kind, self._rot, nx, self._py):
                self._px = nx
                return self.step_s * _MOVE_FRAC
        if self._fits(kind, self._rot, self._px, self._py + 1):
            self._py += 1
            lined_up = self._rot == rot and self._px == col
            return self.step_s * (_DROP_FRAC if lined_up else 1.0)
        self._lock()
        return self.step_s

    def _update(self, dt: float) -> None:
        if self._topout_t > 0:
            self._topout_t -= dt
            if self._topout_t <= 0:
                self.board[:] = 0
                self.lines = 0
                self._spawn()
            return
        if self._clear_t > 0:
            self._clear_t -= dt
            if self._clear_t <= 0:
                keep = np.delete(self.board, self._clearing, axis=0)
                pad = np.zeros((len(self._clearing), self.cols), dtype=np.int8)
                self.board = np.vstack([pad, keep])
                self.lines += len(self._clearing)
                self._clearing = []
                self._spawn()
            return
        self._accum += dt
        while self._accum > 0 and self._clear_t <= 0 and self._topout_t <= 0:
            self._accum -= self._step()

    # ------------------------------------------------------------ drawing

    def _blit(self, out, kind: int, gx: float, gy: float) -> None:
        c = self.cell
        x, y = int(gx), int(gy)
        if y < 0 or x < 0 or y + c > self.height or x + c > self.width:
            return
        out[y : y + c, x : x + c] = self.tiles[kind]

    def frame(self, t: float, dt: float) -> np.ndarray:
        self._update(min(dt, 0.1))
        c = self.cell
        out = np.zeros((self.height, self.width, 3), dtype=np.float32)
        x0, y0 = self.x_off, self.y_off
        x1, y1 = x0 + self.cols * c, y0 + self.rows * c
        out[max(0, y0 - 1) : y1 + 1, max(0, x0 - 1)] = self.frame_rgb
        out[max(0, y0 - 1) : y1 + 1, min(self.width - 1, x1)] = self.frame_rgb
        if y1 < self.height:
            out[y1, max(0, x0 - 1) : x1 + 1] = self.frame_rgb
        if c >= 4:
            out[y0:y1, x0:x1] = np.full(3, 10.0, dtype=np.float32) * self.settings.gain
            out[y0:y1:c, x0:x1] += 6 * self.settings.gain
            out[y0:y1, x0:x1:c] += 6 * self.settings.gain

        ys, xs = np.nonzero(self.board)
        for y, x in zip(ys, xs):
            self._blit(out, int(self.board[y, x]) - 1, x0 + x * c, y0 + y * c)
        if self._clearing:
            on = int(self._clear_t * 16) % 2 == 0
            for row in self._clearing:
                if on:
                    out[y0 + row * c : y0 + (row + 1) * c, x0:x1] = 235 * self.settings.gain
        elif self._topout_t <= 0:
            for x, y in self._cells(self._kind, self._rot, self._px, self._py):
                self._blit(out, self._kind, x0 + x * c, y0 + y * c)
        if self._topout_t > 0:
            fill = int(self.rows * (1 - self._topout_t / _TOPOUT_S))
            out[y1 - fill * c : y1, x0:x1] *= 0.35

        for x, y in _TETROMINOES[self._next][0]:
            self._blit(out, self._next, self.preview_x + x * c, self.preview_y + y * c)
        return np.clip(out, 0, 255).astype(np.uint8)


class TetrisMode(EffectMode):
    mode_id = "tetris"
    field_class = TetrisField
    tick_interval = 0.03
