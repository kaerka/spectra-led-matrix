"""Falling — a flailing stick figure tumbles down an endless cave with parallax walls."""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw

from display.modes.effect_base import EffectField, EffectMode

_SCROLL = (0.35, 0.6, 1.0, 1.6)  # canvas heights per second (front wall layer)
_FIG = 0.30  # figure height as share of the short side


def _profile(n: int, rng: np.random.Generator, octaves=((0.004, 1.0), (0.013, 0.45), (0.05, 0.18))) -> np.ndarray:
    """Smooth periodic 1-D noise in [0, 1] built from a few sine octaves."""
    y = np.arange(n, dtype=np.float32)
    out = np.zeros(n, dtype=np.float32)
    for freq, amp in octaves:
        k = max(1, round(freq * n))
        for _ in range(2):
            out += amp * np.sin(2 * np.pi * k * y / n + rng.uniform(0, 2 * np.pi)) / 2
    out += 0.06 * rng.uniform(-1, 1, n).astype(np.float32)
    out -= out.min()
    return out / max(1e-6, out.max())


class _Layer:
    def __init__(self, field: "FallingField", depth: float) -> None:
        w, h = field.width, field.height
        self.depth = depth
        self.period = 4 * h
        rng = field.rng
        width_frac = 0.12 + 0.22 * depth
        self.left = (0.02 + width_frac * _profile(self.period, rng)) * w
        self.right = (0.02 + width_frac * _profile(self.period, rng)) * w
        self.color = field.wall * (0.25 + 0.75 * (1 - depth))
        self.edge = np.minimum(255, self.color * 1.6 + 10)
        self.speed = field.scroll * (1 - 0.6 * depth)
        self.offset = float(rng.uniform(0, self.period))
        self.xs = np.arange(w, dtype=np.float32)[None, :]

    def paint(self, out: np.ndarray, dt: float) -> None:
        self.offset = (self.offset + self.speed * dt) % self.period
        h, w = out.shape[:2]
        rows = ((np.arange(h) + self.offset) % self.period).astype(np.int32)
        left = self.left[rows][:, None]
        right = (w - 1 - self.right[rows])[:, None]
        wall = (self.xs <= left) | (self.xs >= right)
        lip = ((self.xs > left - 1.5) & (self.xs <= left)) | ((self.xs < right + 1.5) & (self.xs >= right))
        out[wall] = self.color
        out[lip] = self.edge


class FallingField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        short = min(width, height)
        self.scale = short / 64.0
        self.scroll = _SCROLL[settings.values["speed"]] * height
        gain = settings.gain
        self.fig_rgb = tuple(int(c * gain) for c in settings.stops[0])
        self.wall = np.asarray(settings.stops[1 % len(settings.stops)], dtype=np.float32) * gain
        self.bg_top = self.wall * 0.08
        self.layers = [_Layer(self, 0.8), _Layer(self, 0.4), _Layer(self, 0.0)]
        self.fig_h = _FIG * short
        self.spin = float(self.rng.uniform(0, 2 * np.pi))
        self.spin_rate = float(self.rng.uniform(1.4, 2.6)) * (1 if self.rng.random() < 0.5 else -1)
        self.drift = 0.0
        n = int(30 * self.scale)
        self.dust = np.column_stack(
            (self.rng.uniform(0, width, n), self.rng.uniform(0, height, n), self.rng.uniform(0.3, 1.0, n))
        ).astype(np.float32)
        y = np.linspace(1.0, 0.4, height, dtype=np.float32)[:, None, None]
        self.bg = np.broadcast_to(self.bg_top * y, (height, width, 3)).astype(np.float32)

    def _figure(self, draw: ImageDraw.ImageDraw, t: float) -> None:
        cx = self.width / 2 + math.sin(t * 0.6) * self.width * 0.08
        cy = self.height * 0.45 + math.sin(t * 0.9) * self.height * 0.04
        s = self.fig_h / 2
        a = self.spin
        ca, sa = math.cos(a), math.sin(a)

        def p(x: float, y: float) -> tuple[float, float]:
            return cx + (x * ca - y * sa) * s, cy + (x * sa + y * ca) * s

        flail = t * 11.0
        neck, hip = (0.0, -0.45), (0.0, 0.25)
        width = max(1, int(round(self.scale * 1.1)))
        color = self.fig_rgb
        draw.line([p(*neck), p(*hip)], fill=color, width=width)
        for side, phase in ((-1, 0.0), (1, 1.7)):
            arm = 2.2 + 0.7 * math.sin(flail + phase)
            elbow = (side * 0.32 * math.sin(arm) * 1.0, -0.40 - 0.32 * math.cos(arm))
            hand = (elbow[0] + side * 0.28 * math.sin(arm + 0.6 * math.sin(flail * 1.3 + phase)), elbow[1] - 0.28 * math.cos(arm + 0.5))
            draw.line([p(*neck), p(*elbow), p(*hand)], fill=color, width=width)
            kick = 0.35 + 0.35 * math.sin(flail * 0.8 + phase + 0.9)
            knee = (side * 0.22 * math.sin(kick) + side * 0.06, 0.25 + 0.32 * math.cos(kick))
            foot = (knee[0] + side * 0.05, knee[1] + 0.32)
            draw.line([p(*hip), p(*knee), p(*foot)], fill=color, width=width)
        hx, hy = p(0.0, -0.66)
        r = 0.2 * s
        draw.ellipse([hx - r, hy - r, hx + r, hy + r], outline=color, width=width, fill=(0, 0, 0))
        if self.scale >= 2:
            # Wide-open "O" mouth, facing the way the head points.
            mx, my = p(0.06, -0.62)
            mr = max(1.0, 0.045 * s)
            draw.ellipse([mx - mr, my - mr, mx + mr, my + mr], fill=color)

    def frame(self, t: float, dt: float) -> np.ndarray:
        dt = min(dt, 0.1)
        self.spin += self.spin_rate * dt
        out = self.bg.copy()
        d = self.dust
        d[:, 1] -= self.scroll * 1.3 * d[:, 2] * dt
        wrap = d[:, 1] < 0
        d[wrap, 1] += self.height
        d[wrap, 0] = self.rng.uniform(0, self.width, int(wrap.sum()))
        streak = max(2, int(self.scroll * 0.03))
        for k in range(streak):
            ys = (d[:, 1] + k).astype(np.int32)
            xs = d[:, 0].astype(np.int32)
            ok = (ys >= 0) & (ys < self.height)
            out[ys[ok], xs[ok]] = np.maximum(out[ys[ok], xs[ok]], self.wall[None, :] * 0.5 * d[ok, 2:3] * (1 - k / streak))
        for layer in self.layers:
            layer.paint(out, dt)
        img = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
        self._figure(ImageDraw.Draw(img), t)
        return np.asarray(img)


class FallingMode(EffectMode):
    mode_id = "falling"
    field_class = FallingField
    tick_interval = 0.033
