"""Self-playing Breakout — smooth ball physics, aimed paddle, brick shards, rebuilds."""

from __future__ import annotations

import math

import numpy as np

from display.modes.effect_base import EffectField, EffectMode

_BALL_SPEED = (0.45, 0.70, 1.0, 1.45)  # canvas heights per second
_LIVES = 3
_PAUSE_S = 1.0
_CLEAR_S = 1.5


class BreakoutField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        gain = settings.gain
        stops = settings.stops
        self.ball_rgb = np.asarray(stops[0], dtype=np.float32) * gain
        self.paddle_rgb = self.ball_rgb * 0.85
        bricks = stops[1:] or stops
        self.brick_rgbs = [np.asarray(c, dtype=np.float32) * gain for c in bricks[:4]]

        short = min(width, height)
        self.u = u = max(1, round(short / 64))
        self.cols = 8 if width < 96 else 12
        self.n_rows = 2 * len(self.brick_rgbs) if short >= 96 else len(self.brick_rgbs)
        self.gap = 1
        self.bw = (width - 2 * u) // self.cols
        self.bx0 = (width - self.bw * self.cols) // 2
        self.bh = max(2, 2 * u)
        self.top = max(3, round(height * 0.12))
        self.ball = max(2, u + 1)
        self.pad_w = max(10, round(width * 0.15))
        self.pad_h = max(2, u + 1)
        self.pad_y = height - self.pad_h - max(2, u * 2)
        self.base_speed = _BALL_SPEED[settings.values["speed"]] * height
        self.pad_speed = self.base_speed * 1.3
        self.shards: list[list] = []
        self._new_wall()

    def _new_wall(self) -> None:
        self.bricks = np.ones((self.n_rows, self.cols), dtype=bool)
        self.lives = _LIVES
        self.clear_t = 0.0
        self.pad_x = self.width / 2.0
        self._new_ball()

    def _new_ball(self) -> None:
        self.bx, self.by = self.pad_x, self.pad_y - self.ball
        ang = float(self.rng.uniform(-0.7, 0.7))
        self.speed = self.base_speed
        self.vx = self.speed * math.sin(ang)
        self.vy = -self.speed * math.cos(ang)
        self.pause = _PAUSE_S
        self.aim = self.pad_x

    def _brick_rect(self, r: int, c: int) -> tuple[float, float, float, float]:
        x0 = self.bx0 + c * self.bw
        y0 = self.top + r * (self.bh + self.gap)
        return x0, y0, x0 + self.bw - self.gap, y0 + self.bh

    def _plan_aim(self) -> None:
        if self.vy <= 0:
            self.aim = self.bx
            return
        t = (self.pad_y - self.ball / 2 - self.by) / self.vy
        x = self.bx + self.vx * t
        lo, hi = self.ball / 2, self.width - self.ball / 2
        span = hi - lo
        x = (x - lo) % (2 * span)
        land = lo + (2 * span - x if x > span else x)
        cols = np.flatnonzero(self.bricks.any(axis=0))
        target_x = (self.bx0 + (cols.mean() + 0.5) * self.bw) if cols.size else self.width / 2
        lean = max(-1.0, min(1.0, (target_x - land) / (self.width / 2)))
        wild = 0.7 if self.rng.random() < 0.06 else 0.15
        jitter = float(self.rng.uniform(-wild, wild))
        self.aim = land - (lean * 0.35 + jitter) * self.pad_w

    def _hit_bricks(self) -> None:
        r = self.ball / 2
        row0 = int((self.by - r - self.top) // (self.bh + self.gap))
        row1 = int((self.by + r - self.top) // (self.bh + self.gap))
        col0 = int((self.bx - r - self.bx0) // self.bw)
        col1 = int((self.bx + r - self.bx0) // self.bw)
        for row in range(max(0, row0), min(self.n_rows - 1, row1) + 1):
            for col in range(max(0, col0), min(self.cols - 1, col1) + 1):
                if not self.bricks[row, col]:
                    continue
                x0, y0, x1, y1 = self._brick_rect(row, col)
                if self.bx + r < x0 or self.bx - r > x1 or self.by + r < y0 or self.by - r > y1:
                    continue
                self.bricks[row, col] = False
                self._shatter(row, col)
                pen_x = min(self.bx + r - x0, x1 - (self.bx - r))
                pen_y = min(self.by + r - y0, y1 - (self.by - r))
                if pen_x < pen_y:
                    self.vx = -self.vx
                else:
                    self.vy = -self.vy
                self.speed = min(self.base_speed * 1.5, self.speed * 1.01)
                norm = math.hypot(self.vx, self.vy)
                self.vx, self.vy = self.vx * self.speed / norm, self.vy * self.speed / norm
                return

    def _shatter(self, row: int, col: int) -> None:
        x0, y0, x1, y1 = self._brick_rect(row, col)
        rgb = self.brick_rgbs[(row * len(self.brick_rgbs)) // self.n_rows]
        n = 6 if self.u > 1 else 3
        for _ in range(n):
            self.shards.append(
                [
                    float(self.rng.uniform(x0, x1)),
                    float(self.rng.uniform(y0, y1)),
                    float(self.rng.normal(0, 20 * self.u)),
                    float(self.rng.uniform(-10, 10) * self.u),
                    1.0,
                    rgb,
                ]
            )

    def _update(self, dt: float) -> None:
        gravity = 60.0 * self.u
        for s in self.shards:
            s[0] += s[2] * dt
            s[1] += s[3] * dt
            s[3] += gravity * dt
            s[4] -= dt * 1.2
        self.shards = [s for s in self.shards if s[4] > 0 and s[1] < self.height]

        if self.clear_t > 0:
            self.clear_t -= dt
            if self.clear_t <= 0:
                self._new_wall()
            return
        step = self.pad_speed * dt
        self.pad_x += max(-step, min(step, self.aim - self.pad_x))
        self.pad_x = min(self.width - self.pad_w / 2, max(self.pad_w / 2, self.pad_x))
        if self.pause > 0:
            self.pause -= dt
            self.bx = self.pad_x
            return

        r = self.ball / 2
        steps = max(1, math.ceil(self.speed * dt / max(1.0, self.bh / 2)))
        h = dt / steps
        for _ in range(steps):
            was_down = self.vy > 0
            self.bx += self.vx * h
            self.by += self.vy * h
            if self.bx < r:
                self.bx, self.vx = r, abs(self.vx)
            elif self.bx > self.width - r:
                self.bx, self.vx = self.width - r, -abs(self.vx)
            if self.by < r:
                self.by, self.vy = r, abs(self.vy)
            self._hit_bricks()
            if self.vy > 0 and not was_down:
                self._plan_aim()
            if self.vy > 0 and self.pad_y - r <= self.by <= self.pad_y + self.pad_h:
                if abs(self.bx - self.pad_x) <= self.pad_w / 2 + r:
                    hit = (self.bx - self.pad_x) / (self.pad_w / 2)
                    ang = max(-1.0, min(1.0, hit)) * 1.05
                    self.vx = self.speed * math.sin(ang)
                    self.vy = -self.speed * math.cos(ang)
                    self.by = self.pad_y - r
            if self.by > self.height + self.ball:
                self.lives -= 1
                if self.lives <= 0:
                    self._new_wall()
                else:
                    self._new_ball()
                return
        if not self.bricks.any():
            self.clear_t = _CLEAR_S

    @staticmethod
    def _fill(out, x0, y0, x1, y1, rgb) -> None:
        h, w = out.shape[:2]
        x0, y0 = max(0, int(round(x0))), max(0, int(round(y0)))
        x1, y1 = min(w, int(round(x1))), min(h, int(round(y1)))
        if x1 > x0 and y1 > y0:
            out[y0:y1, x0:x1] = rgb

    def frame(self, t: float, dt: float) -> np.ndarray:
        self._update(min(dt, 0.1))
        out = np.zeros((self.height, self.width, 3), dtype=np.float32)
        flash = self.clear_t > 0 and int(self.clear_t * 6) % 2
        per = max(1, self.n_rows // len(self.brick_rgbs))
        for row in range(self.n_rows):
            rgb = self.brick_rgbs[min(len(self.brick_rgbs) - 1, row // per)]
            for col in np.flatnonzero(self.bricks[row]):
                x0, y0, x1, y1 = self._brick_rect(row, int(col))
                self._fill(out, x0, y0, x1, y1, rgb)
                if self.u > 1:
                    self._fill(out, x0, y0, x1, y0 + 1, np.minimum(255, rgb * 1.35))
        for x, y, _, _, life, rgb in self.shards:
            self._fill(out, x, y, x + max(1, self.u // 2 + 1), y + max(1, self.u // 2 + 1), rgb * life)
        if flash:
            out *= 0.3
        half = self.pad_w / 2
        self._fill(out, self.pad_x - half, self.pad_y, self.pad_x + half, self.pad_y + self.pad_h, self.paddle_rgb)
        for k in range(self.lives - 1):
            x = self.u * 2 + k * (self.ball + self.u * 2)
            self._fill(out, x, self.u, x + self.ball, self.u + self.ball, self.paddle_rgb * 0.5)
        if self.clear_t <= 0:
            r = self.ball / 2
            self._fill(out, self.bx - r, self.by - r, self.bx + r, self.by + r, self.ball_rgb)
        return np.clip(out, 0, 255).astype(np.uint8)


class BreakoutMode(EffectMode):
    mode_id = "breakout"
    field_class = BreakoutField
    tick_interval = 0.02
