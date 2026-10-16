from datetime import datetime

import numpy as np
import pytest

from display.modes.analog_clock import render_analog_clock
from display.modes.matrix_rain import RainField
from display.modes.matrix_rain_config import (
    RAIN_PRESETS,
    matrix_rain_config_for_api,
    resolve_rain_color,
    resolve_rain_speed,
)


def test_rain_color_defaults_to_green():
    assert resolve_rain_color(None) == RAIN_PRESETS["green"]
    assert matrix_rain_config_for_api({})["preset"] == "green"


def test_custom_color_wins_and_is_clamped():
    cfg = {"preset": "amber", "color": [300, -5, 10]}
    assert resolve_rain_color(cfg) == (255, 0, 10)
    api = matrix_rain_config_for_api({"color": [1, 2, 3]})
    assert api["preset"] is None and api["color"] == [1, 2, 3]


def test_speed_clamped():
    assert resolve_rain_speed({"speed": 9}) == 3
    assert resolve_rain_speed({"speed": "x"}) == 1


@pytest.mark.parametrize("size", [(64, 64), (128, 64), (192, 192)])
def test_rain_fills_canvas_in_chosen_color(size):
    w, h = size
    field = RainField(w, h, speed=2, color=(255, 0, 0), seed=3)
    for _ in range(120):
        field.step(0.03)
    frame = field.render()
    assert frame.shape == (h, w, 3)
    lit = frame[frame.sum(axis=2) > 0]
    assert len(lit) > w * h * 0.03
    # Trails are pure red; only the white-ish heads carry green/blue.
    assert np.median(lit[:, 0]) > 0 and np.median(lit[:, 1]) == 0


@pytest.mark.parametrize("size", [(64, 64), (128, 64)])
def test_analog_clock_renders_hands(size):
    w, h = size
    frame = np.asarray(render_analog_clock(datetime(2026, 10, 9, 10, 9, 30), w, h))
    assert frame.shape == (h, w, 3)
    red = (frame[..., 0] > 150) & (frame[..., 1] < 90)
    assert red.sum() > 5  # second hand + centre cap
