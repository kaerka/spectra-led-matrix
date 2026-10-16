"""Matrix digital rain — glyph columns falling down the canvas.

Glyphs are random pixel patterns rather than font characters, so the look holds
from one 64x64 panel (3x5 glyphs) to the 192x192 walls (5x7 glyphs).
"""

from __future__ import annotations

import time
from typing import Optional

import numpy as np
from PIL import Image

from display.matrix_config import CANVAS_H, CANVAS_W
from display.modes.matrix_rain_config import (
    drop_speed_range,
    rain_density,
    resolve_rain_color,
    resolve_rain_speed,
)
from display.pillow_compat import set_pillow_image
from display.state import load_state

GLYPH_BANK = 96
GLYPH_MUTATE_PER_SEC = 0.4    # chance per second that a lit glyph flickers to another
TRAIL_HALF_LIFE_S = 0.35
HEAD_WHITE = 0.75             # how far the leading glyph is pushed towards white


def glyph_size(width: int, height: int) -> tuple[int, int]:
    """(glyph_w, glyph_h); the cell adds a 1px gap on each axis."""
    return (3, 5) if min(width, height) < 128 else (5, 7)


def make_glyph_bank(gw: int, gh: int, rng: np.random.Generator, count: int = GLYPH_BANK) -> np.ndarray:
    """Random glyphs, left-right symmetric about half the time, never near-empty."""
    bank = np.zeros((count, gh, gw), dtype=bool)
    for i in range(count):
        while True:
            g = rng.random((gh, gw)) < 0.5
            if rng.random() < 0.5:
                half = (gw + 1) // 2
                g[:, gw - half:] = g[:, :half][:, ::-1]
            if g.sum() >= (gw * gh) // 3:
                break
        bank[i] = g
    return bank


class RainField:
    """Glyph grid plus falling drops; renders to an RGB numpy frame."""

    def __init__(self, width: int, height: int, speed: int, color, seed: Optional[int] = None) -> None:
        self.width, self.height = width, height
        self.rng = np.random.default_rng(seed)
        self.gw, self.gh = glyph_size(width, height)
        self.cw, self.ch = self.gw + 1, self.gh + 1
        self.cols = max(1, (width + 1) // self.cw)
        self.rows = max(1, height // self.ch + 1)
        self.x_off = (width - (self.cols * self.cw - 1)) // 2
        # Tuned on one 64x64 panel (11 rows); taller grids get faster, longer drops.
        self.scale = max(1.0, (self.rows / 11) ** 0.5)
        self.half_life = TRAIL_HALF_LIFE_S * self.scale
        self.bank = make_glyph_bank(self.gw, self.gh, self.rng)
        self.glyph = self.rng.integers(0, len(self.bank), (self.rows, self.cols))
        self.level = np.zeros((self.rows, self.cols), dtype=np.float32)
        self.head = np.zeros((self.rows, self.cols), dtype=bool)
        self.set_style(speed, color)
        # Stagger the start so the screen fills in from the top.
        self.drop_y = -self.rng.random(self.cols) * self.rows * 1.5
        self.drop_v = self.rng.uniform(*self.speed_range, self.cols)
        self.active = self.rng.random(self.cols) < self.density

    def set_style(self, speed: int, color) -> None:
        lo, hi = drop_speed_range(speed)
        self.speed_range = (lo * self.scale, hi * self.scale)
        self.density = rain_density(speed)
        self.color = np.array(color, dtype=np.float32)

    def _respawn(self, cols: np.ndarray) -> None:
        n = len(cols)
        self.drop_y[cols] = -self.rng.random(n) * self.rows * 0.75
        self.drop_v[cols] = self.rng.uniform(*self.speed_range, n)
        self.active[cols] = self.rng.random(n) < self.density

    def step(self, dt: float) -> None:
        self.level *= np.float32(0.5 ** (dt / self.half_life))
        self.head[:] = False

        prev = np.floor(self.drop_y).astype(int)
        self.drop_y += self.drop_v * dt
        cur = np.floor(self.drop_y).astype(int)
        for c in np.flatnonzero(self.active):
            for r in range(max(prev[c] + 1, 0), min(cur[c], self.rows - 1) + 1):
                self.level[r, c] = 1.0
                self.glyph[r, c] = self.rng.integers(len(self.bank))
            if 0 <= cur[c] < self.rows:
                self.head[cur[c], c] = True

        lit = self.level > 0.05
        flicker = lit & (self.rng.random(self.level.shape) < GLYPH_MUTATE_PER_SEC * dt)
        self.glyph[flicker] = self.rng.integers(0, len(self.bank), int(flicker.sum()))

        done = np.flatnonzero(self.drop_y > self.rows + self.rows * 0.5)
        if len(done):
            self._respawn(done)

    def render(self) -> np.ndarray:
        # (rows, cols, gh, gw) glyph pixels -> full-resolution mask with 1px gaps.
        cells = np.zeros((self.rows, self.cols, self.ch, self.cw), dtype=np.float32)
        cells[:, :, : self.gh, : self.gw] = self.bank[self.glyph]
        level = self.level ** 1.6  # perceptual fade: long dim tail, bright front
        cells *= level[:, :, None, None]
        mask = cells.transpose(0, 2, 1, 3).reshape(self.rows * self.ch, self.cols * self.cw)

        head = np.repeat(np.repeat(self.head, self.ch, 0), self.cw, 1).astype(np.float32)
        rgb = mask[..., None] * self.color
        white = (mask * head * HEAD_WHITE)[..., None]
        rgb = rgb * (1 - white) + 255.0 * white

        out = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        h = min(self.height, rgb.shape[0])
        w = min(self.width - self.x_off, rgb.shape[1])
        out[:h, self.x_off:self.x_off + w] = np.clip(rgb[:h, :w], 0, 255).astype(np.uint8)
        return out


def _config_from_state() -> Optional[dict]:
    state = load_state()
    cfg = (state.mode_config or {}).get("matrix_rain")
    return cfg if isinstance(cfg, dict) else None


class MatrixRainMode:
    tick_interval = 0.03

    def setup(self, matrix) -> None:
        cfg = _config_from_state()
        self._field = RainField(CANVAS_W, CANVAS_H, resolve_rain_speed(cfg), resolve_rain_color(cfg))
        self._last = time.monotonic()

    def teardown(self) -> None:
        pass

    def tick(self, matrix, canvas):
        now = time.monotonic()
        self._field.step(min(0.1, now - self._last))
        self._last = now
        set_pillow_image(canvas, Image.fromarray(self._field.render()))
        return matrix.SwapOnVSync(canvas)
