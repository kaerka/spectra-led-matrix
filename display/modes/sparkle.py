"""Sparkle — blinkenlights: every light twinkles or blinks on its own rhythm.

Lights are single pixels or a grid of lamps. Each light keeps a personal pace
(log-normal around the speed setting) and is on for ``density`` of the time.
Twinkle fades each flash in and out with a fresh colour; Blink switches hard
on and off and keeps one colour per lamp, like a front panel.
"""

from __future__ import annotations

import numpy as np

from display.modes.effect_base import EffectField, EffectMode, gradient_lut

_DUTY = (0.02, 0.06, 0.15, 0.35)
_ON_SECONDS = (1.6, 0.8, 0.4, 0.15)


def lamp_cell(size: int, width: int, height: int) -> int:
    """Grid pitch in pixels for the Pixels / Lamps / Big lamps setting."""
    short = min(width, height)
    if size == 0:
        return 1
    if size == 1:
        return max(2, round(short / 32))
    return max(4, round(short / 12))


def lamp_mask(cell: int) -> np.ndarray:
    """(cell, cell) lamp footprint: 1px gap from 3px pitch, rounded from 6px."""
    mask = np.ones((cell, cell), dtype=np.float32)
    if cell >= 3:
        mask[-1, :] = 0
        mask[:, -1] = 0
    if cell >= 6:
        lit = cell - 1
        c = (lit - 1) / 2
        yy, xx = np.mgrid[0:lit, 0:lit]
        mask[:lit, :lit] = ((yy - c) ** 2 + (xx - c) ** 2 <= (lit / 2) ** 2 + 0.5)
    return mask


class SparkleField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        self.blink = values["style"] == 1
        self.duty = _DUTY[values["density"]]
        self.on_s = _ON_SECONDS[values["speed"]]
        self.cell = lamp_cell(values["size"], width, height)
        self.rows, self.cols = max(1, height // self.cell), max(1, width // self.cell)
        self.y_off = (height - self.rows * self.cell) // 2
        self.x_off = (width - self.cols * self.cell) // 2
        self.mask = lamp_mask(self.cell)

        shape = (self.rows, self.cols)
        self.pace = np.exp(self.rng.normal(0.0, 0.5, shape)).astype(np.float32)
        self.on = self.rng.random(shape) < self.duty
        self.start = np.zeros(shape, dtype=np.float32)
        self.length = self._on_length(self.pace)
        # Random phase so the screen starts mid-pattern rather than all at once.
        self.start[self.on] = -self.rng.random(int(self.on.sum())) * self.length[self.on]
        self.next_flip = np.where(self.on, self.start + self.length, self._off_length(self.pace))
        self.color = self._pick_colors(shape)

    def _on_length(self, pace: np.ndarray) -> np.ndarray:
        return (self.on_s * pace * self.rng.uniform(0.6, 1.4, pace.shape)).astype(np.float32)

    def _off_length(self, pace: np.ndarray) -> np.ndarray:
        mean_off = self.on_s * (1 - self.duty) / self.duty
        return (pace * self.rng.exponential(mean_off, pace.shape)).astype(np.float32)

    def _pick_colors(self, shape) -> np.ndarray:
        s = self.settings
        if s.continuous:
            lut = gradient_lut(s.stops, 256)
            return lut[self.rng.integers(0, 256, shape)]
        stops = np.asarray(s.stops, dtype=np.float32)
        return stops[self.rng.integers(0, len(stops), shape)]

    def _advance(self, t: float) -> None:
        due = self.next_flip <= t
        if not due.any():
            return
        turning_on = due & ~self.on
        turning_off = due & self.on
        n_on = int(turning_on.sum())
        if n_on:
            self.start[turning_on] = t
            self.length[turning_on] = self._on_length(self.pace[turning_on])
            self.next_flip[turning_on] = t + self.length[turning_on]
            if not self.blink:
                self.color[turning_on] = self._pick_colors(n_on)
        if turning_off.any():
            self.next_flip[turning_off] = t + self._off_length(self.pace[turning_off])
        self.on[due] = ~self.on[due]

    def levels(self, t: float) -> np.ndarray:
        if self.blink:
            return self.on.astype(np.float32)
        age = np.clip((t - self.start) / self.length, 0.0, 1.0)
        return np.where(self.on, np.sin(np.pi * age) ** 2, 0.0).astype(np.float32)

    def frame(self, t: float, dt: float) -> np.ndarray:
        self._advance(t)
        rgb = self.color * (self.levels(t) * self.settings.gain)[..., None]
        if self.cell > 1:
            rgb = np.repeat(np.repeat(rgb, self.cell, 0), self.cell, 1)
            rgb *= np.tile(self.mask, (self.rows, self.cols))[..., None]
        out = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        h, w = rgb.shape[:2]
        out[self.y_off:self.y_off + h, self.x_off:self.x_off + w] = np.clip(rgb, 0, 255).astype(np.uint8)
        return out


class SparkleMode(EffectMode):
    mode_id = "sparkle"
    field_class = SparkleField
