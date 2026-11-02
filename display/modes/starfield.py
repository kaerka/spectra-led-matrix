"""Win95-style starfield — fly through space sized to the panel canvas.

Perspective projection of particles along Z; intensity scales density/speed/gain.
Color modes: white, warm, cool, rainbow, depth gradient, dual palette.
Stars are anti-aliased sub-pixel points ("Fine") or soft discs ("Classic"),
with optional motion streaks and occasional hyperspace jumps.
"""

from __future__ import annotations

import random
from typing import Optional, Tuple

import numpy as np
from PIL import Image

from display.matrix_config import CANVAS_H, CANVAS_W
from display.modes.color_rotate import (
    color_rotate_hz,
    hue_shift_rgb,
    resolve_color_rotate_speed,
)
from display.modes.starfield_config import (
    resolve_color_mode,
    resolve_jumps,
    resolve_max_radius,
    resolve_output_gain,
    resolve_speed,
    resolve_star_count,
    resolve_star_size,
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
_Z_STEP = 0.012  # z travelled per tick at speed 1.0

# Trail length in ticks of travel, per trail choice (Off/Short/Long/Streaks).
_TRAIL_TICKS = (0.0, 2.5, 6.0, 14.0)
_MAX_TRAIL_SAMPLES = 28

# Hyperspace jump: seconds between jumps per choice (Off/Occasional/Frequent).
_JUMP_GAP_S = (None, (45.0, 90.0), (15.0, 30.0))
_JUMP_PEAK = 7.0
_JUMP_RAMP_S, _JUMP_HOLD_S, _JUMP_FADE_S = 1.2, 1.6, 2.4

# Classic size: soft disc up to max_radius; Fine: point + dim cross for the nearest.
_FINE_CROSS_FROM = 0.8


def _config_from_state() -> Optional[dict]:
    state = load_state()
    if not state.mode_config:
        return None
    cfg = state.mode_config.get("starfield")
    return cfg if isinstance(cfg, dict) else None


def _lerp(a: np.ndarray, b: np.ndarray, t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)[:, None]
    return a * (1.0 - t) + b * t


def _hsv_to_rgb(h: np.ndarray, s: np.ndarray, v: np.ndarray) -> np.ndarray:
    k = (np.array([5.0, 3.0, 1.0], dtype=np.float32)[None, :] + h[:, None] * 6.0) % 6.0
    f = np.clip(np.minimum(k, 4.0 - k), 0.0, 1.0)
    return (v[:, None] - v[:, None] * s[:, None] * f) * 255.0


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
        self.z -= np.float32(speed * _Z_STEP)
        dead = self.z <= _Z_NEAR
        if np.any(dead):
            self._respawn(np.flatnonzero(dead), far=False)

    def screen(self, z: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        inv = 1.0 / np.maximum(z, _Z_NEAR)
        return self.cx + self.x * self.focal * inv, self.cy + self.y * self.focal * inv

    def project(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        sx, sy = self.screen(self.z)
        depth_t = (_Z_FAR - self.z) / (_Z_FAR - _Z_NEAR)
        return sx, sy, np.clip(depth_t, 0.0, 1.0)


class _Splatter:
    """Collects sub-pixel splats for a frame, then sums them in one pass."""

    def __init__(self, w: int, h: int) -> None:
        self.w, self.h = w, h
        self._idx: list = []
        self._rgb: list = []

    def add(self, x: np.ndarray, y: np.ndarray, rgb: np.ndarray) -> None:
        """Add ``rgb`` at sub-pixel (x, y), split bilinearly over 4 pixels."""
        x0 = np.floor(x).astype(np.int32)
        y0 = np.floor(y).astype(np.int32)
        fx = (x - x0)[:, None].astype(np.float32)
        fy = (y - y0)[:, None].astype(np.float32)
        for dx, dy, wt in (
            (0, 0, (1 - fx) * (1 - fy)),
            (1, 0, fx * (1 - fy)),
            (0, 1, (1 - fx) * fy),
            (1, 1, fx * fy),
        ):
            px, py = x0 + dx, y0 + dy
            ok = (px >= 0) & (px < self.w) & (py >= 0) & (py < self.h)
            self._idx.append((py * self.w + px)[ok])
            self._rgb.append((rgb * wt)[ok])

    def image(self, gain: float) -> np.ndarray:
        out = np.zeros((self.h * self.w, 3), dtype=np.float32)
        if self._idx:
            idx = np.concatenate(self._idx)
            rgb = np.concatenate(self._rgb)
            for c in range(3):
                out[:, c] = np.bincount(idx, weights=rgb[:, c], minlength=self.h * self.w)
        return np.clip(out * gain, 0.0, 255.0).astype(np.uint8).reshape(self.h, self.w, 3)


class StarfieldMode:
    tick_interval = 0.016

    def setup(self, matrix) -> None:
        self._matrix = matrix
        self._display_w = CANVAS_W
        self._display_h = CANVAS_H
        self._apply_config(_config_from_state())
        self._sim = StarfieldSim(self._display_w, self._display_h, self._star_count)
        # Intro from deep space: most stars start far so the field blooms in.
        self._sim.z = (
            np.random.random(self._sim.count).astype(np.float32) * 0.35 + (_Z_FAR - 0.35)
        )
        self._t = 0.0
        self._jump_start: Optional[float] = None
        self._next_jump = self._schedule_jump(0.0)

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
        self._star_size = resolve_star_size(cfg)
        self._trail_ticks = _TRAIL_TICKS[resolve_trail(cfg)]
        self._jumps = resolve_jumps(cfg)
        self._rotate_speed = resolve_color_rotate_speed(cfg)
        self._rotate_hz = color_rotate_hz(self._rotate_speed)
        self._hue_phase = 0.0

    def _schedule_jump(self, now: float) -> Optional[float]:
        gap = _JUMP_GAP_S[self._jumps]
        return None if gap is None else now + random.uniform(*gap)

    def _boost(self) -> float:
        """Speed multiplier for the current hyperspace jump (1.0 when cruising)."""
        if self._jump_start is None:
            if self._next_jump is None or self._t < self._next_jump:
                return 1.0
            self._jump_start = self._t
        e = self._t - self._jump_start
        if e < _JUMP_RAMP_S:
            k = (e / _JUMP_RAMP_S) ** 2
        elif e < _JUMP_RAMP_S + _JUMP_HOLD_S:
            k = 1.0
        elif e < _JUMP_RAMP_S + _JUMP_HOLD_S + _JUMP_FADE_S:
            u = (e - _JUMP_RAMP_S - _JUMP_HOLD_S) / _JUMP_FADE_S
            k = (1.0 - u) ** 2
        else:
            self._jump_start = None
            self._next_jump = self._schedule_jump(self._t)
            return 1.0
        return 1.0 + (_JUMP_PEAK - 1.0) * k

    def _colors(self, depth_t: np.ndarray, hue: np.ndarray) -> np.ndarray:
        mode = self._color_mode
        shift = self._hue_phase if self._rotate_hz > 0 and mode != "rainbow" else 0.0

        def stop(c: Color) -> np.ndarray:
            return np.asarray(hue_shift_rgb(c, shift) if shift else c, dtype=np.float32)

        near, mid, far = (stop(self._stops[k]) for k in ("near", "mid", "far"))
        n = len(depth_t)
        if mode == "white":
            base = np.broadcast_to(stop((255, 255, 255)), (n, 3))
        elif mode == "warm":
            base = _lerp(stop((120, 40, 10)), near, 0.35 + 0.65 * depth_t)
        elif mode == "cool":
            base = _lerp(far, near, depth_t)
        elif mode == "rainbow":
            base = _hsv_to_rgb((hue + self._hue_phase) % 1.0, 0.55 + 0.35 * depth_t, 0.75 + 0.25 * depth_t)
        elif mode == "dual":
            base = np.where((hue < 0.5)[:, None], near, mid)
        else:
            base = np.where(
                (depth_t < 0.5)[:, None],
                _lerp(far, mid, depth_t * 2.0),
                _lerp(mid, near, (depth_t - 0.5) * 2.0),
            )
        return base * (0.25 + 0.75 * depth_t)[:, None]

    def _render(self, step: float, boost: float) -> Image.Image:
        splat = _Splatter(self._display_w, self._display_h)
        sim = self._sim
        sx, sy, depth_t = sim.project()
        w, h = self._display_w, self._display_h
        vis = (sx > -2) & (sy > -2) & (sx < w + 1) & (sy < h + 1)
        if not np.any(vis):
            return Image.fromarray(np.zeros((h, w, 3), dtype=np.uint8))
        sx, sy, d = sx[vis], sy[vis], depth_t[vis]
        rgb = self._colors(d, sim.hue[vis])
        # Jumps brighten a little so the streaks read as light, not smears.
        if boost > 1.0:
            rgb = rgb * (1.0 + 0.25 * (boost - 1.0) / (_JUMP_PEAK - 1.0))

        trail_ticks = self._trail_ticks * boost if self._trail_ticks else (2.0 * boost if boost > 1.5 else 0.0)
        if trail_ticks > 0:
            z_prev = np.minimum(sim.z[vis] + np.float32(step * trail_ticks), _Z_FAR)
            px, py = sim.cx + sim.x[vis] * sim.focal / z_prev, sim.cy + sim.y[vis] * sim.focal / z_prev
            length = np.hypot(sx - px, sy - py)
            samples = int(min(_MAX_TRAIL_SAMPLES, max(1.0, float(length.max()) * 1.5)))
            for k in range(1, samples + 1):
                u = k / samples
                fade = (1.0 - u) * 0.55
                splat.add(sx + (px - sx) * u, sy + (py - sy) * u, rgb * fade)

        if self._star_size == 0:
            splat.add(sx, sy, rgb)
            near = d > _FINE_CROSS_FROM
            if np.any(near):
                glow = rgb[near] * ((d[near] - _FINE_CROSS_FROM) / (1.0 - _FINE_CROSS_FROM) * 0.35)[:, None]
                for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    splat.add(sx[near] + ox, sy[near] + oy, glow)
        else:
            radius = 0.4 + d * self._max_radius
            splat.add(sx, sy, rgb)
            rmax = int(np.ceil(radius.max()))
            for oy in range(-rmax, rmax + 1):
                for ox in range(-rmax, rmax + 1):
                    if ox == 0 and oy == 0:
                        continue
                    dist = float(np.hypot(ox, oy))
                    inside = radius >= dist
                    if np.any(inside):
                        splat.add(sx[inside] + ox, sy[inside] + oy, rgb[inside] * 0.55)

        return Image.fromarray(splat.image(self._gain))

    def tick(self, matrix, canvas):
        self._t += self.tick_interval
        if self._rotate_hz > 0:
            self._hue_phase = (self._hue_phase + self._rotate_hz * self.tick_interval) % 1.0
        boost = self._boost()
        step = self._speed * boost * _Z_STEP
        self._sim.update(self._speed * boost)
        frame = self._render(step, boost)
        set_pillow_image(canvas, frame)
        return matrix.SwapOnVSync(canvas)
