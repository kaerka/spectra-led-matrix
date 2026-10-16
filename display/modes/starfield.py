"""Win95-style starfield — fly through space sized to the panel canvas.

Perspective projection of particles along Z; intensity scales density/speed/gain.
Color modes: white, warm, cool, rainbow, depth gradient, dual palette.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
from PIL import Image
from rgbmatrix import RGBMatrix

from display.matrix import CANVAS_H, CANVAS_W
from display.modes.color_rotate import (
    color_rotate_hz,
    hue_shift_rgb,
    resolve_color_rotate_speed,
)
from display.modes.starfield_config import (
    resolve_color_mode,
    resolve_max_radius,
    resolve_output_gain,
    resolve_speed,
    resolve_star_count,
    resolve_starfield_intensity,
    resolve_starfield_stops,
    resolve_trail,
)
from display.pillow_compat import set_pillow_image
from display.state import load_state

Color = Tuple[int, int, int]

_Z_NEAR = 0.12
_Z_FAR = 1.0
_XY_SPAN = 1.0


def _config_from_state() -> Optional[dict]:
    state = load_state()
    if not state.mode_config:
        return None
    cfg = state.mode_config.get("starfield")
    return cfg if isinstance(cfg, dict) else None


def _lerp_color(a: Color, b: Color, t: float) -> Color:
    t = max(0.0, min(1.0, t))
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def _hsv_to_rgb(h: float, s: float, v: float) -> Color:
    i = int(h * 6.0) % 6
    f = h * 6.0 - int(h * 6.0)
    p = v * (1.0 - s)
    q = v * (1.0 - f * s)
    t = v * (1.0 - (1.0 - f) * s)
    if i == 0:
        r, g, b = v, t, p
    elif i == 1:
        r, g, b = q, v, p
    elif i == 2:
        r, g, b = p, v, t
    elif i == 3:
        r, g, b = p, q, v
    elif i == 4:
        r, g, b = t, p, v
    else:
        r, g, b = v, p, q
    return (int(r * 255), int(g * 255), int(b * 255))


class StarfieldSim:
    def __init__(self, display_w: int, display_h: int, count: int) -> None:
        self.display_w = display_w
        self.display_h = display_h
        self.cx = (display_w - 1) * 0.5
        self.cy = (display_h - 1) * 0.5
        self.focal = min(display_w, display_h) * 0.55
        self.count = max(1, count)
        self.x = np.zeros(self.count, dtype=np.float32)
        self.y = np.zeros(self.count, dtype=np.float32)
        self.z = np.zeros(self.count, dtype=np.float32)
        self.hue = np.zeros(self.count, dtype=np.float32)
        self._respawn(np.arange(self.count), far=True)

    def _respawn(self, indices: np.ndarray, *, far: bool) -> None:
        n = len(indices)
        if n == 0:
            return
        self.x[indices] = (np.random.random(n).astype(np.float32) * 2.0 - 1.0) * _XY_SPAN
        self.y[indices] = (np.random.random(n).astype(np.float32) * 2.0 - 1.0) * _XY_SPAN
        if far:
            self.z[indices] = (
                np.random.random(n).astype(np.float32) * (_Z_FAR - _Z_NEAR) + _Z_NEAR
            )
        else:
            self.z[indices] = _Z_FAR - np.random.random(n).astype(np.float32) * 0.08
        self.hue[indices] = np.random.random(n).astype(np.float32)

    def update(self, speed: float) -> None:
        self.z -= np.float32(speed) * 0.012
        dead = self.z <= _Z_NEAR
        if np.any(dead):
            self._respawn(np.flatnonzero(dead), far=False)

    def project(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        z = np.maximum(self.z, _Z_NEAR)
        inv = 1.0 / z
        sx = self.cx + self.x * self.focal * inv
        sy = self.cy + self.y * self.focal * inv
        depth_t = (_Z_FAR - z) / (_Z_FAR - _Z_NEAR)
        return sx, sy, np.clip(depth_t, 0.0, 1.0)


class StarfieldMode:
    tick_interval = 0.016

    def setup(self, matrix: RGBMatrix) -> None:
        self._matrix = matrix
        self._display_w = CANVAS_W
        self._display_h = CANVAS_H
        self._rgb = np.zeros((self._display_h, self._display_w, 3), dtype=np.uint8)
        self._apply_config(_config_from_state())
        self._sim = StarfieldSim(self._display_w, self._display_h, self._star_count)
        # Intro from deep space: most stars start far so the field blooms in.
        self._sim.z = (
            np.random.random(self._sim.count).astype(np.float32) * 0.35 + (_Z_FAR - 0.35)
        )

    def teardown(self) -> None:
        pass

    def _apply_config(self, config: Optional[dict]) -> None:
        cfg = dict(config or {})
        self._intensity = resolve_starfield_intensity(cfg)
        self._color_mode = resolve_color_mode(cfg)
        self._stops = resolve_starfield_stops(cfg)
        self._star_count = resolve_star_count(self._intensity)
        self._speed = resolve_speed(self._intensity)
        self._gain = resolve_output_gain(self._intensity)
        self._max_radius = resolve_max_radius(self._intensity)
        self._trail = resolve_trail(self._intensity)
        self._rotate_speed = resolve_color_rotate_speed(cfg)
        self._rotate_hz = color_rotate_hz(self._rotate_speed)
        self._hue_phase = 0.0

    def _advance_color_rotate(self) -> None:
        if self._rotate_hz <= 0:
            return
        self._hue_phase = (self._hue_phase + self._rotate_hz * self.tick_interval) % 1.0

    def _star_color(self, depth_t: float, hue: float) -> Color:
        mode = self._color_mode
        near, mid, far = self._stops["near"], self._stops["mid"], self._stops["far"]
        if mode == "white":
            base = (255, 255, 255)
        elif mode == "warm":
            base = _lerp_color((120, 40, 10), near, 0.35 + 0.65 * depth_t)
        elif mode == "cool":
            base = _lerp_color(far, near, depth_t)
        elif mode == "rainbow":
            base = _hsv_to_rgb(
                (hue + self._hue_phase) % 1.0,
                0.55 + 0.35 * depth_t,
                0.75 + 0.25 * depth_t,
            )
        elif mode == "dual":
            base = near if hue < 0.5 else mid
        elif depth_t < 0.5:
            base = _lerp_color(far, mid, depth_t * 2.0)
        else:
            base = _lerp_color(mid, near, (depth_t - 0.5) * 2.0)
        shade = 0.25 + 0.75 * depth_t
        color = (
            int(base[0] * shade),
            int(base[1] * shade),
            int(base[2] * shade),
        )
        if self._rotate_hz > 0 and mode != "rainbow":
            color = hue_shift_rgb(color, self._hue_phase)
        return color

    def _plot(self, x: int, y: int, color: Color, radius: float) -> None:
        gain = self._gain
        r = max(0, min(255, int(color[0] * gain)))
        g = max(0, min(255, int(color[1] * gain)))
        b = max(0, min(255, int(color[2] * gain)))
        if radius < 0.75:
            if 0 <= x < self._display_w and 0 <= y < self._display_h:
                self._rgb[y, x] = (r, g, b)
            return
        rad = int(round(radius))
        for dy in range(-rad, rad + 1):
            for dx in range(-rad, rad + 1):
                if dx * dx + dy * dy > rad * rad + 1:
                    continue
                px, py = x + dx, y + dy
                if 0 <= px < self._display_w and 0 <= py < self._display_h:
                    fall = 1.0 if (dx == 0 and dy == 0) else 0.55
                    self._rgb[py, px] = (
                        max(self._rgb[py, px, 0], int(r * fall)),
                        max(self._rgb[py, px, 1], int(g * fall)),
                        max(self._rgb[py, px, 2], int(b * fall)),
                    )

    def _render(self) -> Image.Image:
        self._rgb[:] = 0
        sx, sy, depth_t = self._sim.project()
        order = np.argsort(depth_t)
        for i in order:
            x = float(sx[i])
            y = float(sy[i])
            if x < -2 or y < -2 or x >= self._display_w + 2 or y >= self._display_h + 2:
                continue
            d = float(depth_t[i])
            color = self._star_color(d, float(self._sim.hue[i]))
            radius = 0.4 + d * self._max_radius
            xi, yi = int(round(x)), int(round(y))
            self._plot(xi, yi, color, radius)
            if self._trail > 0 and d > 0.2:
                dx = x - self._sim.cx
                dy = y - self._sim.cy
                for step in range(1, self._trail + 1):
                    tx = int(round(x - dx * 0.04 * step))
                    ty = int(round(y - dy * 0.04 * step))
                    dim = (
                        color[0] // (2 + step),
                        color[1] // (2 + step),
                        color[2] // (2 + step),
                    )
                    self._plot(tx, ty, dim, max(0.5, radius * 0.5))
        return Image.fromarray(self._rgb)

    def tick(self, matrix: RGBMatrix, canvas):
        self._advance_color_rotate()
        self._sim.update(self._speed)
        frame = self._render()
        set_pillow_image(canvas, frame)
        return matrix.SwapOnVSync(canvas)
