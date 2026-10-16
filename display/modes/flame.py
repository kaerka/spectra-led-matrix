"""Flame display mode — sparse Galactic Unicorn fire (retuned vs lava)."""

from __future__ import annotations

from display.modes.fire_mode import FireMode


class FlameMode(FireMode):
    mode_id = "flame"
    profile = "flame"
