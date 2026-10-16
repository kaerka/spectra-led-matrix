"""Conway's Game of Life sized to the panel canvas (hzeller rgbmatrix)."""

from __future__ import annotations

import random
import time

from PIL import Image
from rgbmatrix import RGBMatrix

from display.matrix import CANVAS_H, CANVAS_W
from display.pillow_compat import set_pillow_image

# John Conway tribute pattern (from gameoflife.py / xkcd 2293)
CONWAY_ROWS = (
    b"  +++   ",
    b"  + +   ",
    b"  + +   ",
    b"   +    ",
    b"+ +++   ",
    b" + + +  ",
    b"   +  + ",
    b"  + +   ",
    b"  + +   ",
)


def _apply_life_rule(old: bytearray, new: bytearray, width: int, height: int) -> None:
    for y in range(height):
        yyy = y * width
        ym1 = ((y + height - 1) % height) * width
        yp1 = ((y + 1) % height) * width
        xm1 = width - 1
        for x in range(width):
            xp1 = (x + 1) % width
            neighbors = (
                old[xm1 + ym1] + old[xm1 + yyy] + old[xm1 + yp1]
                + old[x + ym1] + old[x + yp1]
                + old[xp1 + ym1] + old[xp1 + yyy] + old[xp1 + yp1]
            )
            idx = x + yyy
            new[idx] = 1 if neighbors == 3 or (neighbors == 2 and old[idx]) else 0
            xm1 = x


def _randomize(board: bytearray, fraction: float = 0.33) -> None:
    for i in range(len(board)):
        board[i] = 1 if random.random() < fraction else 0


def _draw_conway_tribute(board: bytearray, width: int, height: int) -> None:
    for i in range(len(board)):
        board[i] = 0
    pattern_w = len(CONWAY_ROWS[0])
    pattern_h = len(CONWAY_ROWS)
    origin_x = (width - pattern_w) // 2
    origin_y = height - pattern_h - 2
    for row_i, row in enumerate(CONWAY_ROWS):
        y = origin_y + row_i
        if y < 0 or y >= height:
            continue
        for col_i, cell in enumerate(row):
            x = origin_x + col_i
            if x < 0 or x >= width:
                continue
            if cell == ord("+"):
                board[x + y * width] = 1


def _pick_color() -> tuple[int, int, int]:
    r = 0xFF if random.random() > 0.33 else 0
    g = 0xFF if random.random() > 0.33 else 0
    b = 0xFF if random.random() > 0.33 else 0
    return (r, g, b) if (r or g or b) else (0xFF, 0xFF, 0xFF)


def _board_to_image(board: bytearray, width: int, height: int, color: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGB", (width, height), (0, 0, 0))
    pixels = img.load()
    for y in range(height):
        row = y * width
        for x in range(width):
            if board[row + x]:
                pixels[x, y] = color
    return img


class GameOfLifeMode:
    tick_interval = 0.04

    def setup(self, matrix: RGBMatrix) -> None:
        self._matrix = matrix
        self._width = CANVAS_W
        self._height = CANVAS_H
        size = self._width * self._height
        self._b1 = bytearray(size)
        self._b2 = bytearray(size)
        self._color = (0xFF, 0xFF, 0xFF)
        self._use_b1 = True
        self._generations_left = 0
        self._show_tribute()

    def teardown(self) -> None:
        pass

    def _show_tribute(self) -> None:
        _draw_conway_tribute(self._b1, self._width, self._height)
        self._color = (0xFF, 0xFF, 0xFF)
        self._use_b1 = True
        self._generations_left = 80
        self._tribute_until = time.time() + 3.0

    def _start_random_cycle(self) -> None:
        _randomize(self._b1)
        self._color = _pick_color()
        self._use_b1 = True
        self._generations_left = 400

    def tick(self, matrix: RGBMatrix, canvas):
        if time.time() < getattr(self, "_tribute_until", 0):
            board = self._b1
        elif self._generations_left <= 0:
            self._start_random_cycle()
            board = self._b1
        else:
            if self._use_b1:
                _apply_life_rule(self._b1, self._b2, self._width, self._height)
                board = self._b2
                self._use_b1 = False
            else:
                _apply_life_rule(self._b2, self._b1, self._width, self._height)
                board = self._b1
                self._use_b1 = True
            self._generations_left -= 1

        frame = _board_to_image(board, self._width, self._height, self._color)
        set_pillow_image(canvas, frame)
        return matrix.SwapOnVSync(canvas)
