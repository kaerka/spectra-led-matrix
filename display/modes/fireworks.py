"""Fireworks — rockets with spark trails burst into peonies, rings, willows, and crackle."""

from __future__ import annotations

import math

import numpy as np

from display.modes.effect_base import EffectField, EffectMode

_LAUNCHES_PER_SEC = (0.3, 0.7, 1.3, 2.6)
_SPEED = (0.6, 1.0, 1.5, 2.2)
_GRAVITY = 0.30  # canvas heights / s^2
_DRAG = 1.6
_MAX_PARTICLES = 4000
_TRAIL_DECAY = 6.0  # per second; bigger = shorter trails


class FireworksField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        self.launch_rate = _LAUNCHES_PER_SEC[values["rate"]]
        self.speed = _SPEED[values["speed"]]
        self.colors = np.asarray(settings.stops, dtype=np.float32) * settings.gain
        self.gain = settings.gain
        self.short = min(width, height)
        self.big = self.short >= 128
        self.buf = np.zeros((height, width, 3), dtype=np.float32)
        # Particles: x, y, vx, vy, life, max_life, r, g, b, kind (0 spark, 1 rocket, 2 crackle)
        self.p = np.zeros((0, 10), dtype=np.float32)
        self._launch_acc = 0.6
        self._color_i = int(self.rng.integers(len(self.colors)))

    def _add(self, rows: np.ndarray) -> None:
        room = _MAX_PARTICLES - len(self.p)
        if room <= 0:
            return
        self.p = np.vstack([self.p, rows[:room]])

    def _spawn_rocket(self) -> None:
        h = self.height
        x = self.rng.uniform(0.15, 0.85) * self.width
        apex = self.rng.uniform(0.12, 0.45) * h
        g = _GRAVITY * h * self.speed**2
        vy = -math.sqrt(2 * g * (h - apex))
        color = self.colors[self._color_i % len(self.colors)]
        self._color_i += 1 + int(self.rng.integers(2))
        life = -vy / g
        row = np.array([[x, h - 1, self.rng.normal(0, 0.03) * self.width, vy, life, life, *color, 1]], dtype=np.float32)
        self._add(row)

    def _burst(self, x: float, y: float, color: np.ndarray) -> None:
        rng = self.rng
        kind = rng.choice(4, p=(0.4, 0.2, 0.2, 0.2))
        scale = self.short * self.speed
        n = int((90 if self.big else 40) * rng.uniform(0.8, 1.2))
        ang = rng.uniform(0, 2 * np.pi, n)
        if kind == 0:  # peony
            spd = scale * 0.75 * np.sqrt(rng.uniform(0.1, 1.0, n))
            life = rng.uniform(0.9, 1.5, n)
        elif kind == 1:  # ring
            spd = scale * 0.65 * rng.uniform(0.92, 1.0, n)
            ang = np.linspace(0, 2 * np.pi, n, endpoint=False) + rng.uniform(0, 1)
            life = rng.uniform(1.0, 1.3, n)
        elif kind == 2:  # willow: slow, long-lived, gold-ish droop
            spd = scale * 0.35 * np.sqrt(rng.uniform(0.2, 1.0, n))
            life = rng.uniform(2.0, 3.0, n)
            color = np.minimum(255 * self.gain, color * 0.5 + np.array([255, 190, 80]) * self.gain * 0.5)
        else:  # crackle
            spd = scale * 0.6 * np.sqrt(rng.uniform(0.1, 1.0, n))
            life = rng.uniform(0.7, 1.2, n)
        speed = self.speed
        rows = np.zeros((n, 10), dtype=np.float32)
        rows[:, 0] = x
        rows[:, 1] = y
        rows[:, 2] = np.cos(ang) * spd
        rows[:, 3] = np.sin(ang) * spd
        rows[:, 4] = life / speed
        rows[:, 5] = life / speed
        tint = rng.uniform(0.85, 1.1, (n, 1))
        rows[:, 6:9] = np.minimum(255, color[None, :] * tint)
        rows[:, 9] = 2 if kind == 3 else 0
        self._add(rows)
        # Flash at the burst centre.
        r = max(2, int(self.short * 0.05))
        y0, y1 = max(0, int(y) - r), min(self.height, int(y) + r + 1)
        x0, x1 = max(0, int(x) - r), min(self.width, int(x) + r + 1)
        if y1 > y0 and x1 > x0:
            yy, xx = np.ogrid[y0:y1, x0:x1]
            glow = np.clip(1 - ((xx - x) ** 2 + (yy - y) ** 2) / (r * r), 0, 1)[..., None]
            self.buf[y0:y1, x0:x1] += glow * (color * 0.6 + 60 * self.gain)

    def _update(self, dt: float) -> None:
        self._launch_acc += self.launch_rate * dt * (0.5 + self.rng.random())
        while self._launch_acc >= 1.0:
            self._launch_acc -= 1.0
            self._spawn_rocket()
        p = self.p
        if not len(p):
            return
        g = _GRAVITY * self.height * self.speed**2
        rocket = p[:, 9] == 1
        drag = np.where(rocket, 1.0, math.exp(-_DRAG * self.speed * dt)).astype(np.float32)
        p[:, 2] *= drag
        p[:, 3] = p[:, 3] * drag + g * dt
        p[:, 0] += p[:, 2] * dt
        p[:, 1] += p[:, 3] * dt
        p[:, 4] -= dt

        done = rocket & ((p[:, 4] <= 0) | (p[:, 3] >= 0))
        bursts = p[done]
        trails = p[rocket & ~done]
        alive = (p[:, 4] > 0) & ~done
        alive &= (p[:, 0] >= -2) & (p[:, 0] < self.width + 2) & (p[:, 1] < self.height + 2)
        self.p = p[alive]
        for b in bursts:
            self._burst(float(b[0]), float(b[1]), b[6:9].copy())
        if len(trails):
            k = len(trails)
            sparks = np.zeros((k, 10), dtype=np.float32)
            sparks[:, 0] = trails[:, 0] + self.rng.normal(0, 0.4, k)
            sparks[:, 1] = trails[:, 1] + self.rng.uniform(0, 2, k)
            sparks[:, 2] = self.rng.normal(0, 0.04 * self.short, k)
            sparks[:, 3] = self.rng.uniform(0, 0.1 * self.short, k)
            sparks[:, 4] = sparks[:, 5] = self.rng.uniform(0.15, 0.4, k)
            sparks[:, 6:9] = np.array([255, 200, 120], dtype=np.float32) * self.gain * 0.6
            self._add(sparks)

    def frame(self, t: float, dt: float) -> np.ndarray:
        dt = min(dt, 0.1)
        self._update(dt)
        buf = self.buf
        buf *= math.exp(-_TRAIL_DECAY * dt)
        p = self.p
        if len(p):
            xi = np.round(p[:, 0]).astype(np.int32)
            yi = np.round(p[:, 1]).astype(np.int32)
            ok = (xi >= 0) & (xi < self.width) & (yi >= 0) & (yi < self.height)
            frac = np.clip(p[:, 4] / np.maximum(p[:, 5], 1e-3), 0, 1)
            bright = np.where(p[:, 9] == 1, 1.3, np.minimum(1.0, frac * 1.6))
            crackle = p[:, 9] == 2
            if crackle.any():
                twinkle = self.rng.random(len(p)) < 0.45
                bright = np.where(crackle & (frac < 0.6), np.where(twinkle, 1.6, 0.0), bright)
            rgb = p[:, 6:9] * bright[:, None]
            xi, yi, rgb = xi[ok], yi[ok], rgb[ok]
            np.maximum.at(buf, (yi, xi), rgb)
            if self.big:
                heads = bright[ok] > 0.5
                for dx, dy in ((1, 0), (0, 1)):
                    x2 = np.minimum(xi[heads] + dx, self.width - 1)
                    y2 = np.minimum(yi[heads] + dy, self.height - 1)
                    np.maximum.at(buf, (y2, x2), rgb[heads] * 0.55)
        return np.clip(buf, 0, 255).astype(np.uint8)


class FireworksMode(EffectMode):
    mode_id = "fireworks"
    field_class = FireworksField
    tick_interval = 0.033
