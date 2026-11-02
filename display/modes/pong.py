"""Self-playing Pong — smooth pixel-space rally, arcade score digits, games to 11."""

from __future__ import annotations

import math

import numpy as np

from display.modes.effect_base import EffectField, EffectMode

_BALL_SPEED = (0.55, 0.85, 1.25, 1.8)  # canvas widths per second
_SERVE_S = 0.9
_WIN = 11
_GAME_OVER_S = 2.5

_DIGITS = (
    "111101101101111", "010110010010111", "111001111100111", "111001111001111",
    "101101111001001", "111100111001111", "111100111101111", "111001001001001",
    "111101111101111", "111101111001111",
)


class PongField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        gain = settings.gain
        stops = settings.stops
        self.left_rgb = np.asarray(stops[0], dtype=np.float32) * gain
        self.right_rgb = np.asarray(stops[1 % len(stops)], dtype=np.float32) * gain
        mix = (self.left_rgb + self.right_rgb) * 0.5
        self.ball_rgb = mix if mix.sum() > 8 else np.full(3, 220.0, dtype=np.float32) * gain
        self.net_rgb = self.ball_rgb * 0.35

        u = max(1, round(min(width, height) / 48))
        self.u = u
        self.ball = 2 * u if u > 1 else 2
        self.pad_w = max(2, u)
        self.pad_h = max(8, height // 6)
        self.margin = max(2, 2 * u)
        self.speed = _BALL_SPEED[settings.values["speed"]] * width
        self.pad_speed = self.speed * 0.9
        self.digit = max(2, u)
        self.score = [0, 0]
        self.left_y = self.right_y = height / 2.0
        self.left_aim = self.right_aim = height / 2.0
        self.over_t = 0.0
        self._serve(int(self.rng.integers(2)))

    def _serve(self, toward: int) -> None:
        self.bx, self.by = self.width / 2.0, float(self.rng.uniform(0.25, 0.75) * self.height)
        ang = float(self.rng.uniform(-0.6, 0.6))
        direction = 1 if toward == 1 else -1
        self.vx = direction * self.speed * 0.75 * math.cos(ang)
        self.vy = self.speed * 0.75 * math.sin(ang)
        self.serve_t = _SERVE_S
        self._plan()

    def _predict_y(self, x_target: float) -> float:
        if abs(self.vx) < 1e-3:
            return self.by
        t = (x_target - self.bx) / self.vx
        y = self.by + self.vy * t
        lo, hi = self.ball / 2, self.height - self.ball / 2
        span = hi - lo
        y = (y - lo) % (2 * span)
        return lo + (2 * span - y if y > span else y)

    def _plan(self) -> None:
        # Aim to hit the ball with an off-centre part of the paddle, sometimes badly.
        sloppiness = self.pad_h * (0.75 if self.rng.random() < 0.18 else 0.35)
        offset = float(self.rng.uniform(-sloppiness, sloppiness))
        if self.vx > 0:
            self.right_aim = self._predict_y(self.width - self.margin - self.pad_w) + offset
            self.left_aim = self.height / 2
        else:
            self.left_aim = self._predict_y(self.margin + self.pad_w) + offset
            self.right_aim = self.height / 2

    def _move_paddles(self, dt: float) -> None:
        step = self.pad_speed * dt
        half = self.pad_h / 2
        for side in ("left", "right"):
            y = getattr(self, f"{side}_y")
            aim = getattr(self, f"{side}_aim")
            y += max(-step, min(step, aim - y))
            setattr(self, f"{side}_y", min(self.height - half, max(half, y)))

    def _bounce(self, paddle_y: float, right: bool) -> bool:
        if abs(self.by - paddle_y) > self.pad_h / 2 + self.ball / 2:
            return False
        hit = (self.by - paddle_y) / (self.pad_h / 2)
        ang = max(-1.0, min(1.0, hit)) * 0.95
        spd = min(self.speed * 1.4, math.hypot(self.vx, self.vy) * 1.04)
        self.vx = (-1 if right else 1) * spd * math.cos(ang)
        self.vy = spd * math.sin(ang)
        self._plan()
        return True

    def _update(self, dt: float) -> None:
        if self.over_t > 0:
            self.over_t -= dt
            if self.over_t <= 0:
                self.score = [0, 0]
                self._serve(int(self.rng.integers(2)))
            return
        self._move_paddles(dt)
        if self.serve_t > 0:
            self.serve_t -= dt
            return
        steps = max(1, math.ceil(math.hypot(self.vx, self.vy) * dt / max(1.0, self.ball / 2)))
        h = dt / steps
        for _ in range(steps):
            self.bx += self.vx * h
            self.by += self.vy * h
            r = self.ball / 2
            if self.by < r:
                self.by, self.vy = r, abs(self.vy)
            elif self.by > self.height - r:
                self.by, self.vy = self.height - r, -abs(self.vy)
            left_face = self.margin + self.pad_w + r
            right_face = self.width - self.margin - self.pad_w - r
            if self.vx < 0 and left_face - self.pad_w <= self.bx <= left_face:
                if self._bounce(self.left_y, right=False):
                    self.bx = left_face
            elif self.vx > 0 and right_face <= self.bx <= right_face + self.pad_w:
                if self._bounce(self.right_y, right=True):
                    self.bx = right_face
            if self.bx < -self.ball or self.bx > self.width + self.ball:
                scorer = 1 if self.bx < 0 else 0
                self.score[scorer] += 1
                if self.score[scorer] >= _WIN:
                    self.over_t = _GAME_OVER_S
                else:
                    self._serve(toward=1 - scorer)
                return

    # ------------------------------------------------------------ drawing

    @staticmethod
    def _fill(out, x0, y0, x1, y1, rgb) -> None:
        h, w = out.shape[:2]
        x0, y0 = max(0, int(round(x0))), max(0, int(round(y0)))
        x1, y1 = min(w, int(round(x1))), min(h, int(round(y1)))
        if x1 > x0 and y1 > y0:
            out[y0:y1, x0:x1] = rgb

    def _draw_number(self, out, value: int, cx: float, rgb) -> None:
        d = self.digit
        text = str(value)
        total = len(text) * 4 * d - d
        x = cx - total / 2
        y = self.margin + d
        for ch in text:
            bits = _DIGITS[int(ch)]
            for k, bit in enumerate(bits):
                if bit == "1":
                    col, row = k % 3, k // 3
                    self._fill(out, x + col * d, y + row * d, x + (col + 1) * d, y + (row + 1) * d, rgb)
            x += 4 * d

    def frame(self, t: float, dt: float) -> np.ndarray:
        self._update(min(dt, 0.1))
        out = np.zeros((self.height, self.width, 3), dtype=np.float32)
        cx = self.width / 2
        dash = max(2, self.u * 2)
        nw = max(1, self.u // 2 + (self.u > 2))
        nx = int(cx - nw / 2)
        for y in range(0, self.height, dash * 2):
            self._fill(out, nx, y, nx + nw, y + dash, self.net_rgb)

        blink = self.over_t > 0 and int(t * 3) % 2
        if not blink:
            self._draw_number(out, self.score[0], self.width * 0.25, self.left_rgb * 0.8)
            self._draw_number(out, self.score[1], self.width * 0.75, self.right_rgb * 0.8)
        half = self.pad_h / 2
        self._fill(out, self.margin, self.left_y - half, self.margin + self.pad_w, self.left_y + half, self.left_rgb)
        rx = self.width - self.margin - self.pad_w
        self._fill(out, rx, self.right_y - half, rx + self.pad_w, self.right_y + half, self.right_rgb)
        if self.over_t <= 0 and (self.serve_t <= 0 or int(t * 6) % 2):
            r = self.ball / 2
            self._fill(out, self.bx - r, self.by - r, self.bx + r, self.by + r, self.ball_rgb)
        return np.clip(out, 0, 255).astype(np.uint8)


class PongMode(EffectMode):
    mode_id = "pong"
    field_class = PongField
    tick_interval = 0.02
