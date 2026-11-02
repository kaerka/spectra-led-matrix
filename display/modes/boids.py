"""Boids flock under a dusk sky, or a fish tank with seaweed, light rays, and bubbles."""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw

from display.modes.effect_base import EffectField, EffectMode

_FISH_COUNT = (4, 7, 11)  # at 64 px; scaled by sqrt of canvas size
_BIRD_COUNT = (8, 16, 28)
_SPEED = (0.55, 0.85, 1.2, 1.7)
_SIM_DT = 1.0 / 30.0


def _scaled_count(base: int, short: int) -> int:
    return max(3, int(round(base * math.sqrt(short / 64.0))))


class BoidsField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        rng = self.rng
        gain = settings.gain
        stops = settings.stops
        self.fish_tank = values["style"] == 1
        short = min(width, height)
        self.scale = short / 64.0
        self.creature = np.asarray(stops[0], dtype=np.float32) * gain
        self.water = np.asarray(stops[1 % len(stops)], dtype=np.float32) * gain
        self.accent = np.asarray(stops[2 % len(stops)], dtype=np.float32) * gain

        counts = _FISH_COUNT if self.fish_tank else _BIRD_COUNT
        self.n = _scaled_count(counts[values["count"]], short)
        # Pixels per second.
        self.speed = _SPEED[values["speed"]] * (14.0 if self.fish_tank else 22.0) * self.scale

        n = self.n
        self.pos = np.column_stack(
            (rng.uniform(0.15, 0.85, n) * width, rng.uniform(0.15, 0.75, n) * height)
        ).astype(np.float32)
        ang = rng.uniform(0, 2 * np.pi, n)
        if self.fish_tank:
            ang = np.where(rng.random(n) < 0.5, 0.0, np.pi) + rng.uniform(-0.3, 0.3, n)
        self.vel = (np.column_stack((np.cos(ang), np.sin(ang))) * self.speed * 0.7).astype(np.float32)
        self.size = rng.uniform(0.75, 1.25, n).astype(np.float32)
        self.facing = np.sign(self.vel[:, 0]) + (self.vel[:, 0] == 0)
        self.tint = rng.uniform(0.75, 1.15, n).astype(np.float32)
        self.is_accent = rng.random(n) < 0.3
        self.phase = rng.uniform(0, 2 * np.pi, n).astype(np.float32)
        self._accum = 0.0

        self.floor_y = height - max(2, int(round(height * 0.07)))
        self._bg = self._build_background()
        self._ys = np.arange(height, dtype=np.float32)[:, None]
        self._xs = np.arange(width, dtype=np.float32)[None, :]
        self._depth = np.clip(1.0 - self._ys / max(1, self.floor_y), 0.0, 1.0) ** 1.5

        self._weeds = []
        self._bubbles: list[list[float]] = []
        self._bubble_t = 0.0
        if self.fish_tank:
            for _ in range(max(3, int(round(4 * math.sqrt(self.scale))))):
                self._weeds.append(
                    (
                        float(rng.uniform(0.04, 0.96) * width),
                        float(rng.uniform(0.22, 0.45) * height),
                        float(rng.uniform(0, 2 * np.pi)),
                        float(rng.uniform(0.6, 1.0)),
                    )
                )
            self._bubblers = [float(rng.uniform(0.1, 0.9) * width) for _ in range(2)]

    # ---------------------------------------------------------------- scene

    def _build_background(self) -> np.ndarray:
        h, w = self.height, self.width
        y = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None, None]
        if self.fish_tank:
            top, bottom = self.water * 0.42, self.water * 0.10
        else:
            top, bottom = self.water * 0.45, self.water * 0.06
        bg = np.broadcast_to(top * (1 - y) + bottom * y, (h, w, 3)).astype(np.float32)
        if self.fish_tank:
            bg = bg.copy()
            sand = np.asarray((120, 95, 55), dtype=np.float32) * self.settings.gain
            grain = self.rng.uniform(0.55, 1.0, (h - self.floor_y, w, 1)).astype(np.float32)
            bg[self.floor_y :] = sand * grain
        return bg

    def _light_rays(self, t: float) -> np.ndarray:
        # sin(a*x + b*y - c*t) split into separable sin/cos terms.
        u = 0.09 / self.scale * self._xs - 0.35 * t
        v = 0.035 / self.scale * self._ys
        rays = np.sin(u) * np.cos(v) + np.cos(u) * np.sin(v)
        u2 = 0.047 / self.scale * self._xs + 0.22 * t
        rays2 = np.sin(u2) * np.cos(v * 0.6) + np.cos(u2) * np.sin(v * 0.6)
        light = np.maximum(0.0, rays + rays2 - 0.6) * self._depth
        return 1.0 + 0.55 * light

    # ----------------------------------------------------------- simulation

    def _step(self) -> None:
        n = self.n
        pos, vel = self.pos, self.vel
        w, h = self.width, self.height
        radius = (0.30 if self.fish_tank else 0.22) * min(w, h)
        sep_r = (0.10 if self.fish_tank else 0.09) * min(w, h)

        diff = pos[:, None, :] - pos[None, :, :]
        d2 = (diff * diff).sum(axis=2)
        np.fill_diagonal(d2, np.inf)
        neigh = (d2 < radius * radius).astype(np.float32)
        cnt = neigh.sum(axis=1, keepdims=True)
        has = cnt > 0
        cnt = np.maximum(cnt, 1.0)
        close = (d2 < sep_r * sep_r).astype(np.float32)
        sep = (diff * (close / np.maximum(d2, 1.0))[..., None]).sum(axis=1) * sep_r * self.speed
        ali = neigh @ vel / cnt - vel
        coh = neigh @ pos / cnt - pos

        if self.fish_tank:
            k_sep, k_ali, k_coh = 0.8, 0.25, 0.10
        else:
            k_sep, k_ali, k_coh = 0.5, 2.0, 0.3
        acc = k_sep * sep + has * (k_ali * ali + k_coh * coh)

        margin = 0.12 * min(w, h)
        top = margin if not self.fish_tank else margin * 0.6
        bottom = (self.floor_y - margin * 0.8) if self.fish_tank else (h - margin)
        push = self.speed * 5.0
        acc[:, 0] += np.where(pos[:, 0] < margin, push, 0.0) - np.where(pos[:, 0] > w - margin, push, 0.0)
        acc[:, 1] += np.where(pos[:, 1] < top, push, 0.0) - np.where(pos[:, 1] > bottom, push, 0.0)

        if self.fish_tank:
            acc[:, 1] -= vel[:, 1] * 1.2
            acc[:, 1] += self.rng.normal(0, self.speed * 0.6, n)
            acc[:, 0] += self.facing * self.speed * 0.4
        else:
            acc += self.rng.normal(0, self.speed * 0.3, (n, 2))

        vel += (acc * _SIM_DT).astype(np.float32)
        spd = np.linalg.norm(vel, axis=1, keepdims=True)
        lo, hi = self.speed * 0.45, self.speed
        vel *= np.clip(spd, lo, hi) / np.maximum(spd, 1e-4)
        pos += vel * _SIM_DT
        pos[:, 0] = np.clip(pos[:, 0], 1, w - 2)
        pos[:, 1] = np.clip(pos[:, 1], 1, (self.floor_y if self.fish_tank else h) - 2)

        flip = (np.sign(vel[:, 0]) != self.facing) & (np.abs(vel[:, 0]) > self.speed * 0.25)
        self.facing = np.where(flip, -self.facing, self.facing)

    def _step_bubbles(self, dt: float) -> None:
        self._bubble_t += dt
        rate = 0.25 / math.sqrt(self.scale)
        while self._bubble_t > rate:
            self._bubble_t -= rate
            if self.rng.random() < 0.85:
                x = self._bubblers[int(self.rng.integers(len(self._bubblers)))]
                y = self.floor_y
            else:
                i = int(self.rng.integers(self.n))
                x, y = float(self.pos[i, 0]), float(self.pos[i, 1])
            size = float(self.rng.uniform(0.6, 1.6))
            self._bubbles.append([x + float(self.rng.normal(0, self.scale)), float(y), size, float(self.rng.uniform(0, 6.3))])
        rise = 16.0 * self.scale
        alive = []
        for b in self._bubbles:
            b[1] -= rise * (0.7 + 0.3 * b[2]) * dt
            b[0] += math.sin(b[1] * 0.12 / self.scale + b[3]) * 4.0 * self.scale * dt
            if b[1] > 0:
                alive.append(b)
        self._bubbles = alive

    # -------------------------------------------------------------- drawing

    def _draw_fish(self, draw: ImageDraw.ImageDraw, i: int, t: float) -> None:
        x, y = float(self.pos[i, 0]), float(self.pos[i, 1])
        length = 9.0 * self.scale * float(self.size[i])
        f = float(self.facing[i])
        base = self.accent if self.is_accent[i] else self.creature
        body = tuple(int(c) for c in np.clip(base * self.tint[i], 0, 255))
        fin = tuple(int(c * 0.6) for c in body)
        wag = math.sin(t * 9.0 + float(self.phase[i])) * 0.12 * length
        hh = 0.24 * length
        nose, rear = x + f * 0.45 * length, x - f * 0.30 * length
        draw.polygon(
            [
                (rear, y),
                (x - f * 0.65 * length, y - 0.30 * length + wag),
                (x - f * 0.58 * length, y + wag * 0.3),
                (x - f * 0.65 * length, y + 0.30 * length + wag),
            ],
            fill=fin,
        )
        draw.ellipse([min(nose, rear - f * 0.1 * length), y - hh, max(nose, rear - f * 0.1 * length), y + hh], fill=body)
        draw.polygon([(x, y - hh * 0.8), (x - f * 0.2 * length, y - hh * 1.5), (x - f * 0.22 * length, y - hh * 0.6)], fill=fin)
        ex, ey = x + f * 0.25 * length, y - hh * 0.25
        if self.scale >= 2:
            r = max(1.0, 0.06 * length)
            draw.ellipse([ex - r, ey - r, ex + r, ey + r], fill=(10, 10, 20))
        else:
            draw.point((ex, ey), fill=(10, 10, 20))

    def _draw_bird(self, draw: ImageDraw.ImageDraw, i: int, t: float) -> None:
        x, y = float(self.pos[i, 0]), float(self.pos[i, 1])
        vx, vy = float(self.vel[i, 0]), float(self.vel[i, 1])
        norm = math.hypot(vx, vy) or 1.0
        dx, dy = vx / norm, vy / norm
        px, py = -dy, dx
        s = 2.2 * self.scale * float(self.size[i])
        flap = 0.55 + 0.45 * math.sin(t * 10.0 + float(self.phase[i]))
        color = tuple(int(c) for c in np.clip(self.creature * self.tint[i], 0, 255))
        tip = (x + dx * s, y + dy * s)
        back = (x - dx * s * 0.4, y - dy * s * 0.4)
        wing_l = (x - dx * s + px * s * flap, y - dy * s + py * s * flap)
        wing_r = (x - dx * s - px * s * flap, y - dy * s - py * s * flap)
        draw.polygon([tip, wing_l, back, wing_r], fill=color)

    def _draw_weeds(self, draw: ImageDraw.ImageDraw, t: float) -> None:
        width = max(1, int(round(self.scale * 0.8)))
        green = np.asarray((40, 150, 70), dtype=np.float32) * self.settings.gain
        for x0, height, phase, shade in self._weeds:
            segs = 8
            pts = []
            for k in range(segs + 1):
                f = k / segs
                sway = math.sin(t * 0.9 + phase + f * 2.5) * 3.0 * self.scale * f
                pts.append((x0 + sway, self.floor_y - f * height))
            color = tuple(int(c) for c in green * shade)
            draw.line(pts, fill=color, width=width)

    def frame(self, t: float, dt: float) -> np.ndarray:
        self._accum += min(dt, 0.1)
        while self._accum >= _SIM_DT:
            self._accum -= _SIM_DT
            self._step()

        if self.fish_tank:
            self._step_bubbles(dt)
            base = self._bg * self._light_rays(t)[..., None]
        else:
            base = self._bg
        img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
        draw = ImageDraw.Draw(img)

        if self.fish_tank:
            self._draw_weeds(draw, t)
            order = np.argsort(self.size)
            for i in order:
                self._draw_fish(draw, int(i), t)
            bubble = tuple(int(c) for c in np.clip(self.water * 0.5 + 120 * self.settings.gain, 0, 255))
            for x, y, size, _ in self._bubbles:
                r = size * 0.9 * self.scale ** 0.6
                if r < 1.2:
                    draw.point((x, y), fill=bubble)
                else:
                    draw.ellipse([x - r, y - r, x + r, y + r], outline=bubble)
        else:
            for i in range(self.n):
                self._draw_bird(draw, i, t)
        return np.asarray(img)


class BoidsMode(EffectMode):
    mode_id = "boids"
    field_class = BoidsField
    tick_interval = 0.033
