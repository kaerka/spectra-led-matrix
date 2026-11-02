"""Self-playing Pong — AI paddles rally until a miss, then reset."""

from __future__ import annotations

import numpy as np

from display.modes.effect_base import EffectField, EffectMode

_STEP_S = (0.045, 0.028, 0.018, 0.011)
_BALL_SPEED = (0.55, 0.85, 1.25, 1.85)  # cells per step (scaled by playfield)


class PongField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        self.step_s = _STEP_S[values["speed"]]
        short = min(width, height)
        self.cell = 2 if short >= 96 else 1
        self.cols = width // self.cell
        self.rows = height // self.cell
        self.x_off = (width - self.cols * self.cell) // 2
        self.y_off = (height - self.rows * self.cell) // 2
        gain = settings.gain
        self.left_rgb = np.asarray(settings.stops[0], dtype=np.float32) * gain
        self.right_rgb = np.asarray(settings.stops[1 % len(settings.stops)], dtype=np.float32) * gain
        mix = (self.left_rgb + self.right_rgb) * 0.5
        self.ball_rgb = mix if mix.sum() > 8 else np.array([220, 220, 220], dtype=np.float32) * gain
        self.net_rgb = self.ball_rgb * 0.45
        self.paddle_h = max(3, self.rows // 5)
        self._ball_spd = _BALL_SPEED[values["speed"]]
        self._accum = 0.0
        self._reset()

    def _reset(self) -> None:
        self.left_y = self.rows // 2 - self.paddle_h // 2
        self.right_y = self.left_y
        self.ball_x = self.cols / 2.0
        self.ball_y = self.rows / 2.0
        ang = float(self.rng.uniform(-0.35, 0.35))
        dir_x = 1 if self.rng.random() < 0.5 else -1
        self.vx = dir_x * self._ball_spd * float(np.cos(ang))
        self.vy = self._ball_spd * float(np.sin(ang))
        if abs(self.vy) < 0.15:
            self.vy = 0.25 * (1 if self.rng.random() < 0.5 else -1)
        self._left_target = self.ball_y
        self._right_target = self.ball_y

    def _move_paddle(self, y: float, target: float) -> float:
        # Laggy tracking — not perfect centering.
        err = target - (y + self.paddle_h / 2)
        err += float(self.rng.uniform(-0.6, 0.6))
        step = max(1.0, self.paddle_h / 3.0)
        if err > step:
            y += step
        elif err < -step:
            y -= step
        return float(np.clip(y, 1, self.rows - self.paddle_h - 1))

    def _step(self) -> None:
        # Predict where the ball will be when it reaches each paddle.
        if self.vx > 0:
            t_hit = (self.cols - 2 - self.ball_x) / max(self.vx, 0.05)
            pred = self.ball_y + self.vy * t_hit
            while pred < 2 or pred > self.rows - 3:
                if pred < 2:
                    pred = 4 - pred
                else:
                    pred = 2 * (self.rows - 3) - pred
            self._right_target = pred + float(self.rng.uniform(-1.2, 1.2))
        else:
            t_hit = (self.ball_x - 1) / max(-self.vx, 0.05)
            pred = self.ball_y + self.vy * t_hit
            while pred < 2 or pred > self.rows - 3:
                if pred < 2:
                    pred = 4 - pred
                else:
                    pred = 2 * (self.rows - 3) - pred
            self._left_target = pred + float(self.rng.uniform(-1.2, 1.2))

        self.left_y = self._move_paddle(self.left_y, self._left_target)
        self.right_y = self._move_paddle(self.right_y, self._right_target)

        self.ball_x += self.vx
        self.ball_y += self.vy

        if self.ball_y <= 0.5:
            self.ball_y = 0.5
            self.vy = abs(self.vy)
        elif self.ball_y >= self.rows - 1.5:
            self.ball_y = self.rows - 1.5
            self.vy = -abs(self.vy)

        by = int(round(self.ball_y))
        # Left paddle at x=0
        if self.ball_x < 1.0:
            if self.left_y <= by < self.left_y + self.paddle_h:
                self.ball_x = 1.0
                self.vx = abs(self.vx) * 1.02
                hit = (by - self.left_y) / max(1, self.paddle_h - 1) - 0.5
                self.vy += hit * 0.35
            else:
                self._reset()
                return
        # Right paddle at x=cols-1
        if self.ball_x > self.cols - 2:
            if self.right_y <= by < self.right_y + self.paddle_h:
                self.ball_x = float(self.cols - 2)
                self.vx = -abs(self.vx) * 1.02
                hit = (by - self.right_y) / max(1, self.paddle_h - 1) - 0.5
                self.vy += hit * 0.35
            else:
                self._reset()
                return

        spd = np.hypot(self.vx, self.vy)
        cap = self._ball_spd * 1.35
        if spd > cap:
            self.vx *= cap / spd
            self.vy *= cap / spd

    def _paint(self) -> np.ndarray:
        grid = np.zeros((self.rows, self.cols, 3), dtype=np.float32)
        # Dashed center net.
        cx = self.cols // 2
        for y in range(1, self.rows - 1):
            if (y // 2) % 2 == 0:
                grid[y, cx] = self.net_rgb
        ly = int(round(self.left_y))
        grid[ly:ly + self.paddle_h, 0] = self.left_rgb
        ry = int(round(self.right_y))
        grid[ry:ry + self.paddle_h, self.cols - 1] = self.right_rgb
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


class PongMode(EffectMode):
    mode_id = "pong"
    field_class = PongField
    tick_interval = 0.03
