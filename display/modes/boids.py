"""Boids flock or fish-tank schooling with optional bubbles."""

from __future__ import annotations

import numpy as np

from display.modes.effect_base import EffectField, EffectMode

_COUNT_BASE = (8, 16, 28)
_MAX_SPEED = (0.55, 0.85, 1.15, 1.65)
_STEPS_PER_S = (25.0, 40.0, 60.0, 90.0)


def _count_for_canvas(count_idx: int, w: int, h: int) -> int:
    base = _COUNT_BASE[count_idx]
    scale = (w * h) / (64.0 * 64.0)
    return max(4, int(round(base * scale)))


class BoidsField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        self.fish_tank = values["style"] == 1
        self.n = _count_for_canvas(values["count"], width, height)
        self.max_speed = _MAX_SPEED[values["speed"]] * (min(width, height) / 64.0)
        self.step_s = 1.0 / _STEPS_PER_S[values["speed"]]
        self.creature_rgb = np.asarray(settings.stops[0], dtype=np.float32) * settings.gain
        self.bg_rgb = np.asarray(settings.stops[1 % len(settings.stops)], dtype=np.float32) * settings.gain
        self.accent_rgb = np.asarray(settings.stops[2 % len(settings.stops)], dtype=np.float32) * settings.gain
        rng = self.rng
        self.pos = rng.uniform(0.15, 0.85, (self.n, 2)).astype(np.float32)
        self.pos[:, 0] *= width
        self.pos[:, 1] *= height
        ang = rng.uniform(0, 2 * np.pi, self.n)
        spd = rng.uniform(0.3, 0.7, self.n) * self.max_speed
        self.vel = np.stack([np.cos(ang), np.sin(ang)], axis=1).astype(np.float32) * spd[:, None]
        if self.fish_tank:
            self.vel[:, 0] *= 1.4
            self.vel[:, 1] *= 0.55
        self._accum = 0.0
        self._bubbles: list[tuple[float, float, float]] = []
        self._bubble_timer = 0.0

    def _wrap(self) -> None:
        w, h = self.width, self.height
        self.pos[:, 0] = np.mod(self.pos[:, 0], w)
        self.pos[:, 1] = np.mod(self.pos[:, 1], h)

    def _bounds_bounce(self) -> None:
        margin = 2.0
        for i in range(self.n):
            for axis, lim in ((0, self.width), (1, self.height)):
                if self.pos[i, axis] < margin:
                    self.pos[i, axis] = margin
                    self.vel[i, axis] *= -1
                elif self.pos[i, axis] > lim - margin:
                    self.pos[i, axis] = lim - margin
                    self.vel[i, axis] *= -1

    def _step_boids(self) -> None:
        n = self.n
        if n < 2:
            return
        pos = self.pos
        vel = self.vel
        # Pairwise distances (n is small).
        diff = pos[:, None, :] - pos[None, :, :]
        dist2 = (diff ** 2).sum(axis=2)
        np.fill_diagonal(dist2, np.inf)
        dist = np.sqrt(dist2)
        neigh = dist < (self.width * 0.18)
        sep = np.zeros((n, 2), dtype=np.float32)
        ali = np.zeros((n, 2), dtype=np.float32)
        coh = np.zeros((n, 2), dtype=np.float32)
        counts = np.zeros(n, dtype=np.float32)
        for i in range(n):
            mask = neigh[i]
            if not mask.any():
                continue
            d = diff[i, mask]
            dist_i = dist[i, mask]
            sep[i] = (d / (dist_i[:, None] ** 2 + 1e-3)).sum(axis=0)
            ali[i] = vel[mask].mean(axis=0)
            coh[i] = pos[mask].mean(axis=0) - pos[i]
            counts[i] = mask.sum()
        w_sep, w_ali, w_coh = 1.2, 0.8, 0.5
        if self.fish_tank:
            w_sep, w_ali, w_coh = 1.0, 1.0, 0.35
        acc = np.zeros((n, 2), dtype=np.float32)
        has = counts > 0
        acc[has] += w_sep * sep[has]
        acc[has] += w_ali * (ali[has] - vel[has])
        acc[has] += w_coh * coh[has] * 0.02
        if self.fish_tank:
            acc[:, 0] += 0.08 * np.sign(vel[:, 0] + 0.01)
            acc[:, 1] += self.rng.normal(0, 0.02, n)
        vel += acc * 0.08
        spd = np.linalg.norm(vel, axis=1, keepdims=True)
        spd = np.maximum(spd, 1e-4)
        cap = self.max_speed
        vel *= np.where(spd > cap, cap / spd, 1.0)
        pos += vel * 0.35
        if self.fish_tank:
            self._wrap()
        else:
            self._bounds_bounce()

    def _spawn_bubble(self) -> None:
        x = float(self.rng.uniform(self.width * 0.1, self.width * 0.9))
        y = float(self.height - 2)
        vy = float(self.rng.uniform(12, 22))
        self._bubbles.append((x, y, vy))

    def _step_bubbles(self, dt: float) -> None:
        if not self.fish_tank:
            self._bubbles.clear()
            return
        self._bubble_timer += dt
        if self._bubble_timer > 0.35 and self.rng.random() < 0.4:
            self._bubble_timer = 0.0
            self._spawn_bubble()
        alive = []
        for x, y, vy in self._bubbles:
            y -= vy * dt
            x += np.sin(y * 0.15) * 8 * dt
            if y > 0:
                alive.append((x, y, vy))
        self._bubbles = alive

    def _draw_triangle(self, out: np.ndarray, x: float, y: float, angle: float, size: float, rgb) -> None:
        c, s = np.cos(angle), np.sin(angle)
        pts = np.array([[size, 0], [-size * 0.6, size * 0.5], [-size * 0.6, -size * 0.5]], dtype=np.float32)
        rot = np.array([[c, -s], [s, c]], dtype=np.float32)
        pts = pts @ rot.T + np.array([x, y], dtype=np.float32)
        p0, p1, p2 = pts

        def edge(ax, ay, bx, by, px, py) -> np.ndarray:
            return (px - ax) * (by - ay) - (py - ay) * (bx - ax)

        minx = max(0, int(np.floor(pts[:, 0].min() - 1)))
        maxx = min(self.width - 1, int(np.ceil(pts[:, 0].max() + 1)))
        miny = max(0, int(np.floor(pts[:, 1].min() - 1)))
        maxy = min(self.height - 1, int(np.ceil(pts[:, 1].max() + 1)))
        for py in range(miny, maxy + 1):
            for px in range(minx, maxx + 1):
                w0 = edge(p1[0], p1[1], p2[0], p2[1], px, py)
                w1 = edge(p2[0], p2[1], p0[0], p0[1], px, py)
                w2 = edge(p0[0], p0[1], p1[0], p1[1], px, py)
                if (w0 >= 0 and w1 >= 0 and w2 >= 0) or (w0 <= 0 and w1 <= 0 and w2 <= 0):
                    out[py, px] = rgb

    def frame(self, t: float, dt: float) -> np.ndarray:
        self._accum += dt
        while self._accum >= self.step_s:
            self._accum -= self.step_s
            self._step_boids()
        self._step_bubbles(dt)
        out = np.broadcast_to(self.bg_rgb, (self.height, self.width, 3)).copy()
        if self.fish_tank:
            # Subtle shimmer on water.
            shimmer = 0.92 + 0.08 * np.sin(
                np.linspace(0, 4 * np.pi, self.width, dtype=np.float32)[None, :]
                + t * 1.2
            )
            out *= shimmer[..., None]
        sz = max(1.5, min(self.width, self.height) / 28.0)
        r = max(1, int(round(sz * 0.55)))
        for i in range(self.n):
            x, y = int(round(self.pos[i, 0])), int(round(self.pos[i, 1]))
            if self.fish_tank or self.n > 48:
                y0, y1 = max(0, y - r), min(self.height, y + r + 1)
                x0, x1 = max(0, x - r), min(self.width, x + r + 1)
                out[y0:y1, x0:x1] = self.creature_rgb
            else:
                ang = float(np.arctan2(self.vel[i, 1], self.vel[i, 0]))
                self._draw_triangle(out, float(self.pos[i, 0]), float(self.pos[i, 1]), ang, sz, self.creature_rgb)
        for x, y, _vy in self._bubbles:
            bx, by = int(x), int(y)
            if 0 <= bx < self.width and 0 <= by < self.height:
                r = 1
                y0, y1 = max(0, by - r), min(self.height, by + r + 1)
                x0, x1 = max(0, bx - r), min(self.width, bx + r + 1)
                out[y0:y1, x0:x1] = self.accent_rgb
        return np.clip(out, 0, 255).astype(np.uint8)


class BoidsMode(EffectMode):
    mode_id = "boids"
    field_class = BoidsField
    tick_interval = 0.033
