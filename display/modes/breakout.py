"""Self-playing Breakout — paddle AI, bricks rebuild when cleared."""

from __future__ import annotations

import numpy as np

from display.modes.effect_base import EffectField, EffectMode

_STEP_S = (0.055, 0.035, 0.022, 0.014)
_BALL_SPD = (0.42, 0.62, 0.92, 1.35)


class BreakoutField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        self.step_s = _STEP_S[values["speed"]]
        short = min(width, height)
        self.cell = 2 if short >= 128 else (2 if short >= 80 else 1)
        self.cols = width // self.cell
        self.rows = height // self.cell
        self.x_off = (width - self.cols * self.cell) // 2
        self.y_off = (height - self.rows * self.cell) // 2
        gain = settings.gain
        self.ball_rgb = np.asarray(settings.stops[0], dtype=np.float32) * gain
        self.paddle_rgb = self.ball_rgb * 0.85
        n_rows = min(4, max(1, len(settings.stops) - 1))
        self.brick_rgbs = [
            np.asarray(settings.stops[1 + i % max(1, len(settings.stops) - 1)], dtype=np.float32) * gain
            for i in range(n_rows)
        ]
        self.n_brick_rows = n_rows
        self.paddle_w = max(4, self.cols // 6)
        self.paddle_y = self.rows - 2
        self._ball_spd = _BALL_SPD[values["speed"]]
        self._accum = 0.0
        self._reset()

    def _reset(self) -> None:
        self.bricks = np.ones((self.n_brick_rows, self.cols), dtype=bool)
        top = 2
        for r in range(self.n_brick_rows):
            self.bricks[r, :] = True
        self._brick_y0 = top
        self.paddle_x = self.cols // 2 - self.paddle_w // 2
        self.ball_x = self.cols / 2.0
        self.ball_y = float(self.paddle_y - 2)
        ang = float(self.rng.uniform(-0.8, 0.8))
        self.vx = self._ball_spd * float(np.sin(ang))
        self.vy = -abs(self._ball_spd * float(np.cos(ang)))

    def _paddle_target(self) -> float:
        t = self.ball_x
        if self.vy > 0:
            t += self.vx * max(0, (self.paddle_y - self.ball_y) / max(self.vy, 0.05))
        return t + float(self.rng.uniform(-1.5, 1.5))

    def _step(self) -> None:
        target = self._paddle_target()
        px = self.paddle_x + self.paddle_w / 2
        err = target - px
        step = max(1.0, self.paddle_w / 4.0)
        if err > step:
            self.paddle_x += int(step)
        elif err < -step:
            self.paddle_x -= int(step)
        self.paddle_x = int(np.clip(self.paddle_x, 1, self.cols - self.paddle_w - 1))

        self.ball_x += self.vx
        self.ball_y += self.vy

        if self.ball_x <= 0.5:
            self.ball_x = 0.5
            self.vx = abs(self.vx)
        elif self.ball_x >= self.cols - 1.5:
            self.ball_x = self.cols - 1.5
            self.vx = -abs(self.vx)

        if self.ball_y <= 0.5:
            self.ball_y = 0.5
            self.vy = abs(self.vy)
        elif self.ball_y >= self.rows - 0.5:
            self._reset()
            return

        bx, by = int(round(self.ball_x)), int(round(self.ball_y))
        # Bricks
        if 0 <= by < self.n_brick_rows + self._brick_y0 and self.vy < 0:
            br = by - self._brick_y0
            if 0 <= br < self.n_brick_rows and 0 <= bx < self.cols and self.bricks[br, bx]:
                self.bricks[br, bx] = False
                self.vy = abs(self.vy)
                if not self.bricks.any():
                    self._reset()
                return

        # Paddle
        if self.vy > 0 and by >= self.paddle_y - 1:
            if self.paddle_x <= bx < self.paddle_x + self.paddle_w:
                self.ball_y = float(self.paddle_y - 1)
                self.vy = -abs(self.vy)
                hit = (bx - self.paddle_x) / max(1, self.paddle_w - 1) - 0.5
                self.vx += hit * 0.5

        spd = np.hypot(self.vx, self.vy)
        cap = self._ball_spd * 1.4
        if spd > cap:
            self.vx *= cap / spd
            self.vy *= cap / spd

    def _paint(self) -> np.ndarray:
        grid = np.zeros((self.rows, self.cols, 3), dtype=np.float32)
        for r in range(self.n_brick_rows):
            y = self._brick_y0 + r
            if y >= self.rows:
                continue
            mask = self.bricks[r]
            if mask.any():
                grid[y, mask] = self.brick_rgbs[r % len(self.brick_rgbs)]
        py = self.paddle_y
        px = self.paddle_x
        grid[py, px:px + self.paddle_w] = self.paddle_rgb
        bx, by = int(round(self.ball_x)), int(round(self.ball_y))
        if 0 <= bx < self.cols and 0 <= by < self.rows:
            grid[by, bx] = self.ball_rgb
        return grid

    def frame(self, t: float, dt: float) -> np.ndarray:
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


class BreakoutMode(EffectMode):
    mode_id = "breakout"
    field_class = BreakoutField
    tick_interval = 0.03
