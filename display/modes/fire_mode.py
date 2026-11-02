"""Shared Galactic Unicorn fire simulation + mode base (flame / lava)."""

from __future__ import annotations

import time
from typing import Optional, Tuple

import numpy as np
from PIL import Image

from display.matrix_config import CANVAS_H, CANVAS_W
from display.modes.color_rotate import (
    color_rotate_hz,
    hue_shift_colors,
    resolve_color_rotate_speed,
)
from display.modes.flame_config import (
    SLOW_BUILD_S,
    FireProfile,
    build_fire_palette_lut,
    resolve_fire_intro,
    resolve_fire_damping,
    resolve_fire_heat_scale,
    resolve_fire_height_px,
    resolve_fire_intensity,
    resolve_fire_output_gain,
    resolve_fire_palette,
    resolve_fire_seed_density,
    resolve_fire_seed_heat,
    resolve_fire_turbulence,
)
from display.pillow_compat import set_pillow_image
from display.state import load_state

# A teardown followed by setup of the same mode within this window is a
# settings change, not a fresh switch.
_HANDOFF_S = 2.0


def _config_from_state(mode_id: str) -> Optional[dict]:
    state = load_state()
    if not state.mode_config:
        return None
    cfg = state.mode_config.get(mode_id)
    return cfg if isinstance(cfg, dict) else None


class GalacticFireSim:
    """Landscape heat rising from the bottom edge."""

    def __init__(
        self,
        display_w: int,
        display_h: int,
        *,
        damping_factor: float = 0.97,
        seed_heat: float = 1.0,
        turbulence: float = 0.06,
        seed_density: float = 1.0,
    ) -> None:
        self.display_w = display_w
        self.display_h = display_h
        self.width = display_w + 2
        self.height = display_h + 4
        self.damping_factor = damping_factor
        self.seed_heat = seed_heat
        self.turbulence = turbulence
        self.seed_density = max(0.01, min(1.0, seed_density))
        self.max_height_px = display_h
        self.heat = np.zeros((self.width, self.height), dtype=np.float32)

    def set_max_height(self, height_px: int) -> None:
        self.max_height_px = max(1, min(self.display_h, height_px))

    def _clamp_height(self) -> None:
        cutoff = self.display_h - self.max_height_px
        if cutoff <= 0:
            return
        self.heat[1 : self.width - 1, :cutoff] = 0.0

    def update(self) -> None:
        heat = self.heat
        w = self.width
        h = self.height

        heat[:, h - 1] = 0.0
        heat[:, h - 2] = 0.0

        seeds = np.random.random(w - 4).astype(np.float32) * self.seed_heat
        if self.seed_density < 1.0:
            mask = (np.random.random(w - 4) < self.seed_density).astype(np.float32)
            seeds *= mask
        heat[2 : w - 2, h - 1] = seeds
        heat[2 : w - 2, h - 2] = seeds * 0.85

        ys = slice(0, h - 2)
        xs = slice(1, w - 1)
        center = heat[xs, ys]
        below = heat[xs, 1 : h - 1]
        below2 = heat[xs, 2:h]
        left = heat[0 : w - 2, 1 : h - 1]
        right = heat[2:w, 1 : h - 1]
        avg = (center + below + below2 + left + right) * 0.2

        if self.turbulence > 0:
            noise = (np.random.random(avg.shape).astype(np.float32) - 0.5) * self.turbulence
            heat[xs, ys] = np.clip(avg * self.damping_factor + noise, 0.0, None)
        else:
            heat[xs, ys] = avg * self.damping_factor

        self._clamp_height()


class FireMode:
    """Base display mode; subclasses set ``mode_id`` / ``profile``."""

    mode_id: str = "flame"
    profile: FireProfile = "flame"
    tick_interval = 0.016
    _handoff: Optional[Tuple[str, float, np.ndarray]] = None

    def setup(self, matrix) -> None:
        self._matrix = matrix
        self._display_w = CANVAS_W
        self._display_h = CANVAS_H
        self._apply_config(_config_from_state(self.mode_id))
        self._sim = GalacticFireSim(
            self._display_w,
            self._display_h,
            damping_factor=self._damping_factor,
            seed_heat=self._seed_heat,
            turbulence=self._turbulence,
            seed_density=self._seed_density,
        )
        self._sim.set_max_height(self._max_height_px)
        self._rgb = np.zeros((self._display_h, self._display_w, 3), dtype=np.uint8)
        self._elapsed = 0.0
        kept = FireMode._handoff
        FireMode._handoff = None
        if (
            kept is not None
            and kept[0] == self.mode_id
            and time.monotonic() - kept[1] < _HANDOFF_S
            and kept[2].shape == self._sim.heat.shape
        ):
            # The runner rebuilds the mode on every settings change; carry the
            # flames over so a colour tweak doesn't replay the intro.
            self._sim.heat = kept[2]
            self._elapsed = SLOW_BUILD_S
        elif self._intro == 2:
            # Steady state takes ~1 tick per px of height; run twice that unseen.
            for _ in range(max(100, 2 * self._display_h)):
                self._sim.update()

    def teardown(self) -> None:
        FireMode._handoff = (self.mode_id, time.monotonic(), self._sim.heat)

    def _apply_config(self, config: Optional[dict]) -> None:
        cfg = dict(config or {})
        profile = self.profile
        self._base_palette = resolve_fire_palette(cfg)
        self._rotate_speed = resolve_color_rotate_speed(cfg)
        self._rotate_hz = color_rotate_hz(self._rotate_speed)
        self._hue_phase = 0.0
        self._rebuild_lut(0.0)
        self._intensity = resolve_fire_intensity(cfg)
        base_damping = float(cfg.get("damping", 0.97))
        self._damping_factor = resolve_fire_damping(
            profile, self._intensity, self._display_h, base_damping
        )
        self._seed_heat = resolve_fire_seed_heat(profile, self._intensity)
        self._turbulence = resolve_fire_turbulence(profile, self._intensity)
        self._heat_scale = resolve_fire_heat_scale(profile, self._intensity)
        self._seed_density = resolve_fire_seed_density(profile, self._intensity)
        self._output_gain = resolve_fire_output_gain(profile, self._intensity)
        self._max_height_px = resolve_fire_height_px(self._intensity, self._display_h)
        self._intro = resolve_fire_intro(cfg)

    def _apply_intro(self) -> None:
        if self._intro != 1 or self._elapsed >= SLOW_BUILD_S:
            return
        self._elapsed += self.tick_interval
        ramp = min(1.0, self._elapsed / SLOW_BUILD_S)
        self._sim.seed_heat = self._seed_heat * (0.15 + 0.85 * ramp * ramp)

    def _rebuild_lut(self, phase: float) -> None:
        palette = (
            hue_shift_colors(self._base_palette, phase)
            if phase
            else self._base_palette
        )
        self._lut = build_fire_palette_lut(palette, profile=self.profile)

    def _advance_color_rotate(self) -> None:
        if self._rotate_hz <= 0:
            return
        self._hue_phase = (self._hue_phase + self._rotate_hz * self.tick_interval) % 1.0
        self._rebuild_lut(self._hue_phase)

    def _render(self) -> Image.Image:
        view = self._sim.heat[1 : self._display_w + 1, : self._display_h]
        idx = np.clip((view * self._heat_scale).astype(np.int32), 0, 255)
        colors = np.transpose(self._lut[idx], (1, 0, 2)).astype(np.float32)
        if self._output_gain < 1.0:
            colors *= self._output_gain
        self._rgb[:] = np.clip(colors, 0, 255).astype(np.uint8)
        # Pillow 9 copies the buffer — rebuild each frame.
        return Image.fromarray(self._rgb)

    def tick(self, matrix, canvas):
        self._advance_color_rotate()
        self._apply_intro()
        self._sim.update()
        frame = self._render()
        set_pillow_image(canvas, frame)
        return matrix.SwapOnVSync(canvas)
