import numpy as np
import pytest

import display.modes.fire_mode as fm
from display.modes.flame import FlameMode
from display.modes.flame_config import SLOW_BUILD_S, flame_config_for_api, resolve_fire_intro
from display.modes.lava import LavaMode


@pytest.fixture(autouse=True)
def _canvas(monkeypatch):
    monkeypatch.setattr(fm, "CANVAS_W", 64)
    monkeypatch.setattr(fm, "CANVAS_H", 64)
    monkeypatch.setattr(fm.FireMode, "_handoff", None)


def _mode(monkeypatch, cls, cfg):
    monkeypatch.setattr(fm, "_config_from_state", lambda mode_id: cfg)
    mode = cls()
    mode.setup(None)
    return mode


def test_intro_resolves_and_reports():
    assert resolve_fire_intro({}) == 0
    assert resolve_fire_intro({"intro": 2}) == 2
    for bad in (3, -1, True, "1"):
        assert resolve_fire_intro({"intro": bad}) == 0
    api = flame_config_for_api({"intro": 1})
    assert api["intro"] == 1 and api["intro_labels"][1] == "Slow build"


def test_natural_starts_cold_instant_starts_burning(monkeypatch):
    cold = _mode(monkeypatch, LavaMode, {"intensity": 3})
    assert cold._sim.heat.max() == 0.0
    cold.teardown()
    fm.FireMode._handoff = None
    warm = _mode(monkeypatch, LavaMode, {"intensity": 3, "intro": 2})
    assert np.asarray(warm._render()).mean() > 20


def test_slow_build_ramps_fuel(monkeypatch):
    mode = _mode(monkeypatch, FlameMode, {"intensity": 3, "intro": 1})
    full = mode._seed_heat
    mode._apply_intro()
    assert mode._sim.seed_heat < 0.2 * full
    mode._elapsed = SLOW_BUILD_S
    mode._apply_intro()
    mode._elapsed = SLOW_BUILD_S - mode.tick_interval
    mode._apply_intro()
    assert mode._sim.seed_heat == pytest.approx(full)


def test_settings_change_keeps_the_flames(monkeypatch):
    mode = _mode(monkeypatch, FlameMode, {"intensity": 3, "intro": 1})
    for _ in range(200):
        mode._sim.update()
    heat = mode._sim.heat.copy()
    mode.teardown()
    again = _mode(monkeypatch, FlameMode, {"intensity": 3, "intro": 1, "preset": "blue"})
    assert np.array_equal(again._sim.heat, heat)
    assert again._elapsed >= SLOW_BUILD_S


def test_switching_profiles_starts_fresh(monkeypatch):
    flame = _mode(monkeypatch, FlameMode, {"intensity": 3})
    for _ in range(100):
        flame._sim.update()
    flame.teardown()
    lava = _mode(monkeypatch, LavaMode, {"intensity": 3})
    assert lava._sim.heat.max() == 0.0
