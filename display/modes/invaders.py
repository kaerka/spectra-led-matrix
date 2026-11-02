"""Space Invaders attract — marching aliens, AI ship dodges and shoots."""

from __future__ import annotations

import numpy as np

from display.modes.effect_base import EffectField, EffectMode

_STEP_S = (0.14, 0.09, 0.055, 0.035)
_ALIEN = np.array(
    [
        [0, 0, 1, 0, 0],
        [0, 1, 1, 1, 0],
        [1, 1, 0, 1, 1],
        [1, 0, 1, 0, 1],
        [0, 1, 0, 1, 0],
    ],
    dtype=np.uint8,
)
_SHIP = np.array([[0, 1, 0], [1, 1, 1], [1, 0, 1]], dtype=np.uint8)


class InvadersField(EffectField):
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
        self.alien_rgb = np.asarray(settings.stops[0], dtype=np.float32) * gain
        self.ship_rgb = np.asarray(settings.stops[1 % len(settings.stops)], dtype=np.float32) * gain
        self.shot_rgb = np.asarray(settings.stops[2 % len(settings.stops)], dtype=np.float32) * gain
        self._accum = 0.0
        self._march_dir = 1
        self._anim = 0
        self._reset()

    def _reset(self) -> None:
        aw, ah = _ALIEN.shape[1], _ALIEN.shape[0]
        n_cols = max(4, min(8, self.cols // (aw + 2)))
        n_rows = max(2, min(4, (self.rows - 10) // (ah + 1)))
        self.alien_w, self.alien_h = aw, ah
        self.alien_grid = np.ones((n_rows, n_cols), dtype=bool)
        self.alien_x = (self.cols - n_cols * (aw + 1)) // 2
        self.alien_y = 3
        self._march_dir = 1
        self._anim = 0
        sw = _SHIP.shape[1]
        self.ship_x = self.cols // 2 - sw // 2
        self.ship_y = self.rows - 4
        self.player_shot: tuple[int, int] | None = None
        self.alien_shots: list[tuple[int, int]] = []

    def _alive_bounds(self) -> tuple[int, int, int, int] | None:
        ys, xs = np.where(self.alien_grid)
        if xs.size == 0:
            return None
        aw, ah = self.alien_w, self.alien_h
        left = self.alien_x + int(xs.min()) * (aw + 1)
        right = self.alien_x + int(xs.max()) * (aw + 1) + aw
        top = self.alien_y + int(ys.min()) * (ah + 1)
        bot = self.alien_y + int(ys.max()) * (ah + 1) + ah
        return left, right, top, bot

    def _ship_target_x(self) -> int:
        threat = None
        for sx, sy in self.alien_shots:
            if abs(sx - (self.ship_x + 1)) <= 2:
                threat = sx
        if threat is not None:
            if threat >= self.ship_x + 1:
                return max(1, self.ship_x - 2)
            return min(self.cols - _SHIP.shape[1] - 1, self.ship_x + 2)
        # Chase nearest alien column for shooting.
        ys, xs = np.where(self.alien_grid)
        if xs.size:
            aw = self.alien_w
            ax = self.alien_x + int(xs[int(np.argmin(np.abs(xs - (self.ship_x // (aw + 1)))))]) * (aw + 1) + aw // 2
            return int(np.clip(ax - 1, 1, self.cols - _SHIP.shape[1] - 1))
        return self.ship_x

    def _step(self) -> None:
        if not self.alien_grid.any():
            self._reset()
            return

        target = self._ship_target_x()
        if self.ship_x < target:
            self.ship_x += 1
        elif self.ship_x > target:
            self.ship_x -= 1

        if self.player_shot is None and self.rng.random() < 0.35:
            self.player_shot = (self.ship_x + 1, self.ship_y - 1)

        if self.player_shot:
            sx, sy = self.player_shot
            sy -= 1
            if sy < 0:
                self.player_shot = None
            else:
                hit = False
                aw, ah = self.alien_w, self.alien_h
                gap = 1
                for r in range(self.alien_grid.shape[0]):
                    for c in range(self.alien_grid.shape[1]):
                        if not self.alien_grid[r, c]:
                            continue
                        ax = self.alien_x + c * (aw + gap)
                        ay = self.alien_y + r * (ah + gap)
                        if ax <= sx < ax + aw and ay <= sy < ay + ah:
                            self.alien_grid[r, c] = False
                            hit = True
                            break
                    if hit:
                        break
                self.player_shot = None if hit else (sx, sy)

        new_shots = []
        for sx, sy in self.alien_shots:
            sy += 1
            if sy >= self.rows:
                continue
            sw = _SHIP.shape[1]
            if self.ship_y <= sy < self.ship_y + 3 and self.ship_x <= sx < self.ship_x + sw:
                self._reset()
                return
            new_shots.append((sx, sy))
        self.alien_shots = new_shots

        if self.rng.random() < 0.08 + 0.02 * self.alien_grid.sum():
            ys, xs = np.where(self.alien_grid)
            i = int(self.rng.integers(0, len(xs)))
            aw, ah = self.alien_w, self.alien_h
            sx = self.alien_x + int(xs[i]) * (aw + 1) + aw // 2
            sy = self.alien_y + int(ys[i]) * (ah + 1) + ah
            self.alien_shots.append((sx, sy))

        bounds = self._alive_bounds()
        if bounds is None:
            self._reset()
            return
        left, right, _top, bot = bounds
        step_down = False
        if self._march_dir > 0 and right >= self.cols - 2:
            self._march_dir = -1
            step_down = True
        elif self._march_dir < 0 and left <= 1:
            self._march_dir = 1
            step_down = True
        if step_down:
            self.alien_y += 1
            if bot + 1 >= self.ship_y:
                self._reset()
                return
        else:
            self.alien_x += self._march_dir
        self._anim ^= 1

    def _blit(self, grid: np.ndarray, sprite: np.ndarray, ox: int, oy: int, rgb: np.ndarray) -> None:
        sh, sw = sprite.shape
        for dy in range(sh):
            y = oy + dy
            if y < 0 or y >= self.rows:
                continue
            for dx in range(sw):
                if not sprite[dy, dx]:
                    continue
                x = ox + dx
                if 0 <= x < self.cols:
                    grid[y, x] = rgb

    def _paint(self) -> np.ndarray:
        grid = np.zeros((self.rows, self.cols, 3), dtype=np.float32)
        aw, ah = self.alien_w, self.alien_h
        gap = 1
        sprite = _ALIEN if self._anim == 0 else np.fliplr(_ALIEN)
        for r in range(self.alien_grid.shape[0]):
            for c in range(self.alien_grid.shape[1]):
                if self.alien_grid[r, c]:
                    ax = self.alien_x + c * (aw + gap)
                    ay = self.alien_y + r * (ah + gap)
                    self._blit(grid, sprite, ax, ay, self.alien_rgb)
        self._blit(grid, _SHIP, self.ship_x, self.ship_y, self.ship_rgb)
        if self.player_shot:
            sx, sy = self.player_shot
            if 0 <= sy < self.rows and 0 <= sx < self.cols:
                grid[sy, sx] = self.shot_rgb
        for sx, sy in self.alien_shots:
            if 0 <= sy < self.rows and 0 <= sx < self.cols:
                grid[sy, sx] = self.shot_rgb * 0.85
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


class InvadersMode(EffectMode):
    mode_id = "invaders"
    field_class = InvadersField
    tick_interval = 0.03
