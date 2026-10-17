"""WOPR tic-tac-toe — perfect play, every game a draw, faster and faster."""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw

from display.bitmap_fonts import draw_ink_centered, load_bdf, text_size
from display.modes.effect_base import EffectField, EffectMode

# Pace: base think time (s) before acceleration; card chance after each game.
_BASE_THINK = (0.55, 0.32, 0.16, 0.07)
_CARD_CHANCE = (0.08, 0.22, 0.45)
_CARD_HOLD = 3.2
_LINES = (
    (0, 1, 2), (3, 4, 5), (6, 7, 8),
    (0, 3, 6), (1, 4, 7), (2, 5, 8),
    (0, 4, 8), (2, 4, 6),
)
_STRANGE = ("A STRANGE GAME.", "THE ONLY WINNING", "MOVE IS", "NOT TO PLAY.")


def _winner(board: tuple) -> int:
    for a, b, c in _LINES:
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    return 0


@lru_cache(maxsize=None)
def _minimax(board: tuple, player: int) -> tuple[int, int | None]:
    """Return (score, best_move) for ``player`` (1=X, -1=O). Score from X's view."""
    w = _winner(board)
    if w:
        return w * 10, None
    empties = [i for i, v in enumerate(board) if v == 0]
    if not empties:
        return 0, None
    best_score = -999 if player == 1 else 999
    best_move = empties[0]
    for i in empties:
        nxt = board[:i] + (player,) + board[i + 1:]
        score, _ = _minimax(nxt, -player)
        if player == 1:
            if score > best_score:
                best_score, best_move = score, i
        elif score < best_score:
            best_score, best_move = score, i
    return best_score, best_move


class WoprField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        self.base_think = _BASE_THINK[values["speed"]]
        self.card_chance = _CARD_CHANCE[values["card"]]
        self.grid_rgb = tuple(int(c) for c in np.asarray(settings.stops[0], dtype=np.float32) * settings.gain)
        self.mark_rgb = tuple(int(c) for c in np.asarray(settings.stops[1 % len(settings.stops)], dtype=np.float32) * settings.gain)
        short = min(width, height)
        self.board_px = max(24, int(short * 0.78))
        self.cell = self.board_px // 3
        self.board_px = self.cell * 3
        self.ox = (width - self.board_px) // 2
        self.oy = (height - self.board_px) // 2
        self.line_w = max(1, self.cell // 12)
        self.mark_pad = max(2, self.cell // 6)
        self._font_name = "tom-thumb" if short < 96 else "5x7"
        self._reset_match()
        self._card_until = -1.0
        self._games = 0

    def _reset_match(self) -> None:
        self.board = [0] * 9
        self.player = 1  # X starts
        self._think_left = self.base_think * 0.6
        self._pause_left = 0.0
        self._finished = False

    def _think_time(self) -> float:
        # Accelerate: after many draws, think times shrink toward a floor.
        factor = max(0.12, 0.92 ** self._games)
        return max(0.02, self.base_think * factor)

    def _play_best(self) -> None:
        # First move: random corner/center for variety (still leads to draws).
        empties = [i for i, v in enumerate(self.board) if v == 0]
        if len(empties) == 9:
            move = int(self.rng.choice([0, 2, 4, 6, 8]))
        else:
            _, move = _minimax(tuple(self.board), self.player)
            if move is None:
                move = empties[0]
        self.board[move] = self.player
        self.player = -self.player
        if _winner(tuple(self.board)) or all(self.board):
            self._finished = True
            self._pause_left = max(0.35, self._think_time() * 2.5)
            self._games += 1

    def _draw_mark(self, img: np.ndarray, cell: int, who: int) -> None:
        r, c = divmod(cell, 3)
        x0 = self.ox + c * self.cell + self.mark_pad
        y0 = self.oy + r * self.cell + self.mark_pad
        x1 = self.ox + (c + 1) * self.cell - self.mark_pad - 1
        y1 = self.oy + (r + 1) * self.cell - self.mark_pad - 1
        color = np.asarray(self.mark_rgb, dtype=np.uint8)
        if who == 1:  # X
            for t in range(self.line_w):
                self._line(img, x0 + t, y0, x1 + t, y1, color)
                self._line(img, x1 - t, y0, x0 - t, y1, color)
        else:  # O
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            rad = min(x1 - x0, y1 - y0) / 2
            self._circle(img, cx, cy, rad, color, self.line_w)

    @staticmethod
    def _line(img, x0, y0, x1, y1, color) -> None:
        h, w = img.shape[:2]
        steps = max(abs(int(x1 - x0)), abs(int(y1 - y0)), 1)
        for i in range(steps + 1):
            t = i / steps
            x = int(round(x0 + (x1 - x0) * t))
            y = int(round(y0 + (y1 - y0) * t))
            if 0 <= x < w and 0 <= y < h:
                img[y, x] = color

    @staticmethod
    def _circle(img, cx, cy, rad, color, thickness) -> None:
        h, w = img.shape[:2]
        yy, xx = np.ogrid[0:h, 0:w]
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        ring = (dist >= rad - thickness) & (dist <= rad + 0.5)
        img[ring] = color

    def _render_board(self) -> np.ndarray:
        out = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        g = np.asarray(self.grid_rgb, dtype=np.uint8)
        # Grid lines.
        for i in (1, 2):
            y = self.oy + i * self.cell
            out[y:y + self.line_w, self.ox:self.ox + self.board_px] = g
            x = self.ox + i * self.cell
            out[self.oy:self.oy + self.board_px, x:x + self.line_w] = g
        for i, who in enumerate(self.board):
            if who:
                self._draw_mark(out, i, who)
        return out

    def _render_card(self) -> np.ndarray:
        img = Image.new("RGB", (self.width, self.height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        try:
            font = load_bdf(self._font_name)
        except FileNotFoundError:
            font = None
        color = self.mark_rgb
        if font is None:
            # Fallback: simple bitmap-free lines via PIL default.
            y = self.height // 4
            for line in _STRANGE:
                draw.text((4, y), line, fill=color)
                y += 12
        else:
            gap = 2 if self.height < 96 else 3
            heights = [text_size(font, line)[1] for line in _STRANGE]
            total = sum(heights) + gap * (len(_STRANGE) - 1)
            y = max(1, (self.height - total) // 2)
            for line, lh in zip(_STRANGE, heights):
                draw_ink_centered(draw, self.width // 2, y, line, font, color)
                y += lh + gap
        return np.asarray(img, dtype=np.uint8)

    def frame(self, t: float, dt: float) -> np.ndarray:
        if self._card_until > t:
            return self._render_card()
        if self._card_until > 0 and t >= self._card_until:
            self._card_until = -1.0
            self._reset_match()

        if self._finished:
            self._pause_left -= dt
            if self._pause_left <= 0:
                if self.rng.random() < self.card_chance:
                    self._card_until = t + _CARD_HOLD
                    return self._render_card()
                self._reset_match()
        else:
            self._think_left -= dt
            if self._think_left <= 0:
                self._play_best()
                if not self._finished:
                    self._think_left = self._think_time()
        return self._render_board()


class WoprMode(EffectMode):
    mode_id = "wopr"
    field_class = WoprField
    tick_interval = 0.04
