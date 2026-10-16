"""Lava display mode — dense heat field (archived pre-split flame look)."""

from __future__ import annotations

from display.modes.fire_mode import FireMode


class LavaMode(FireMode):
    mode_id = "lava"
    profile = "lava"
