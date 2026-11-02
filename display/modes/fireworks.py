"""Fireworks — rockets rise, burst into particles with gravity and fade."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from display.modes.effect_base import EffectField, EffectMode

_LAUNCHES_PER_SEC = (0.25, 0.6, 1.2, 2.5)
_SPEED = (0.55, 1.0, 1.6, 2.4)
_GRAVITY = 22.0
_MAX_PARTICLES = 420


@dataclass
class _Rocket:
    x: float
    y: float
    vy: float
    color: np.ndarray
    fuse: float


@dataclass
class _Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    color: np.ndarray


class FireworksField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        self.launch_rate = _LAUNCHES_PER_SEC[values["rate"]]
        self.speed_mul = _SPEED[values["speed"]]
        self.gain = settings.gain
        stops = np.asarray(settings.stops, dtype=np.float32)
        self.colors = stops
        self._rockets: list[_Rocket] = []
        self._particles: list[_Particle] = []
        self._launch_acc = float(self.rng.random())
        self._color_i = 0

    def _pick_color(self) -> np.ndarray:
        c = self.colors[self._color_i % len(self.colors)] * self.gain
        self._color_i += 1
        return c.astype(np.float32)

    def _spawn_rocket(self) -> None:
        x = self.rng.uniform(self.width * 0.15, self.width * 0.85)
        short = min(self.width, self.height)
        vy = -self.rng.uniform(0.45, 0.72) * short * self.speed_mul
        fuse = self.rng.uniform(0.35, 0.75) / max(0.5, self.speed_mul)
        self._rockets.append(
            _Rocket(x=x, y=float(self.height - 2), vy=vy, color=self._pick_color(), fuse=fuse)
        )

    def _burst(self, x: float, y: float, color: np.ndarray) -> None:
        n = int(self.rng.integers(18, 32))
        short = min(self.width, self.height)
        spd = 0.22 * short * self.speed_mul
        for _ in range(n):
            if len(self._particles) >= _MAX_PARTICLES:
                break
            ang = self.rng.uniform(0, 2 * np.pi)
            v = spd * self.rng.uniform(0.35, 1.0)
            self._particles.append(
                _Particle(
                    x=x,
                    y=y,
                    vx=float(np.cos(ang) * v),
                    vy=float(np.sin(ang) * v),
                    life=self.rng.uniform(0.5, 1.1),
                    color=color,
                )
            )

    def frame(self, t: float, dt: float) -> np.ndarray:
        self._launch_acc += self.launch_rate * dt
        while self._launch_acc >= 1.0:
            self._launch_acc -= 1.0
            self._spawn_rocket()

        next_rockets: list[_Rocket] = []
        short = min(self.width, self.height)
        apex = short * 0.22
        for r in self._rockets:
            r.y += r.vy * dt
            r.vy += _GRAVITY * dt * (short / 64.0)
            r.fuse -= dt
            if r.fuse <= 0 or r.y <= apex or r.vy >= -short * 0.04:
                self._burst(r.x, max(apex, r.y), r.color)
            else:
                next_rockets.append(r)
        self._rockets = next_rockets

        buf = np.zeros((self.height, self.width, 3), dtype=np.float32)
        h, w = self.height, self.width
        for r in self._rockets:
            xi, yi = int(round(r.x)), int(round(r.y))
            if 0 <= xi < w and 0 <= yi < h:
                buf[yi, xi] = np.maximum(buf[yi, xi], r.color * 1.2)

        next_parts: list[_Particle] = []
        for p in self._particles:
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.vy += _GRAVITY * dt * (short / 64.0)
            p.life -= dt
            if p.life <= 0:
                continue
            next_parts.append(p)
            fade = np.clip(p.life / 0.35, 0.0, 1.0)
            xi, yi = int(round(p.x)), int(round(p.y))
            if 0 <= xi < w and 0 <= yi < h:
                buf[yi, xi] = np.maximum(buf[yi, xi], p.color * fade)
        self._particles = next_parts

        return np.clip(buf, 0, 255).astype(np.uint8)


class FireworksMode(EffectMode):
    mode_id = "fireworks"
    field_class = FireworksField
    tick_interval = 0.033
