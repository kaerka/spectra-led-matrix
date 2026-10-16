"""Procedural effects: rainbow, sparkle, lava lamp."""

from __future__ import annotations

import numpy as np
import pytest

from display.modes.effect_config import (
    EFFECTS,
    effect_config_for_api,
    resolve_effect,
    sample_cyclic,
    validate_effect_patch,
)
from display.modes.lava_lamp import LavaLampField
from display.modes.rainbow import RainbowField
from display.modes.sparkle import SparkleField, lamp_cell

FIELDS = {"rainbow": RainbowField, "sparkle": SparkleField, "lava_lamp": LavaLampField}
SIZES = [(64, 64), (128, 64), (192, 192)]


def test_defaults_resolve():
    for mode_id, spec in EFFECTS.items():
        s = resolve_effect(mode_id, None)
        assert s.palette == spec.default_palette
        assert s.gain == spec.gains[-1]
        assert set(s.values) == {o.key for o in spec.options}


def test_custom_colors_win_and_bad_values_fall_back():
    s = resolve_effect("lava_lamp", {"colors": [[1, 2, 3], [4, 5, 6]], "speed": 99})
    assert s.palette is None and s.stops == ((1, 2, 3), (4, 5, 6))
    assert s.values["speed"] == 1
    assert resolve_effect("lava_lamp", {"colors": [[1, 2, 3]]}).palette == "classic"


def test_validate_patch():
    assert validate_effect_patch("rainbow", {"palette": "neon", "speed": 3}) == {"palette": "neon", "speed": 3}
    for bad in ({}, {"palette": "nope"}, {"speed": 4}, {"speed": True}, {"colors": [[0, 0, 0]]},
                {"colors": [[0, 0, 256]] * 4}, {"wat": 1}, {"palette": "neon", "colors": [[0, 0, 0]] * 4}):
        with pytest.raises(ValueError):
            validate_effect_patch("rainbow", bad)


def test_api_shape():
    cfg = effect_config_for_api("rainbow", {"palette": "spectrum"})
    assert len(cfg["colors"]) == 4 and cfg["colors"][0] == [255, 0, 0]
    assert [o["key"] for o in cfg["options"]] == ["speed", "direction", "bands", "brightness"]
    assert sample_cyclic(((0, 0, 0), (255, 255, 255)), 2) == ((0, 0, 0), (255, 255, 255))


@pytest.mark.parametrize("mode_id", list(FIELDS))
@pytest.mark.parametrize("size", SIZES)
def test_renders(mode_id, size):
    w, h = size
    f = FIELDS[mode_id](w, h, resolve_effect(mode_id, None), seed=1)
    for i in range(30):
        frame = f.frame(i * 0.05, 0.05)
    assert frame.shape == (h, w, 3) and frame.dtype == np.uint8
    assert frame.max() > 0


def test_rainbow_flows_from_chosen_corner():
    s = resolve_effect("rainbow", {"palette": "spectrum", "direction": 0})
    f = RainbowField(64, 64, s)
    a = f.frame(0.0, 0.0)
    assert a[0, 0, 0] > 150 and a[0, 0, 1:].max() == 0  # spectrum starts red at top-left
    assert (a[0, 63] == a[63, 0]).all()  # bands run along the anti-diagonal
    later = f.frame(1.0, 1.0)
    assert not (later[0, 0] == a[0, 0]).all()  # and keep moving


def test_brightness_scales_output():
    hi = RainbowField(32, 32, resolve_effect("rainbow", {"brightness": 3})).frame(0, 0)
    night = RainbowField(32, 32, resolve_effect("rainbow", {"brightness": 0})).frame(0, 0)
    assert night.max() < hi.max() * 0.2


def test_sparkle_density_and_blink_colours():
    s = resolve_effect("sparkle", {"density": 3, "style": 1, "palette": "retro"})
    f = SparkleField(64, 64, s, seed=2)
    colours = f.color.copy()
    for i in range(40):
        f.frame(i * 0.1, 0.1)
    assert 0.2 < f.on.mean() < 0.5
    assert (f.color == colours).all()  # blink keeps one colour per lamp
    assert lamp_cell(2, 192, 192) == 16 and lamp_cell(1, 64, 64) == 2
