import numpy as np
import pytest

import display.modes.fire_mode as fm
from display.modes.effect_config import effect_config_for_api, resolve_effect, validate_effect_patch
from display.modes.flame import FlameMode
from display.modes.flame_config import FIRE_THEMES, SLOW_BUILD_S, migrate_fire_config
from display.modes.lava import LavaMode


@pytest.fixture(autouse=True)
def _canvas(monkeypatch):
    monkeypatch.setattr(fm, "CANVAS_W", 64)
    monkeypatch.setattr(fm, "CANVAS_H", 64)
    monkeypatch.setattr(fm.FireMode, "_handoff", None)
    np.random.seed(0)


def _mode(monkeypatch, cls, cfg):
    monkeypatch.setattr(fm, "_config_from_state", lambda mode_id: cfg)
    mode = cls()
    mode.setup(None)
    return mode


def _lit_top(mode, ticks=400):
    """Highest lit row as a share of the canvas height, averaged over frames."""
    for _ in range(ticks):
        mode._sim.update()
    frames = []
    for _ in range(30):
        mode._sim.update()
        mode._frame += 1
        frames.append(np.asarray(mode._render()).astype(np.float32).mean(axis=2))
    lit = (np.mean(frames, axis=0) / mode._output_gain > 25).mean(axis=1) > 0.05
    rows = np.flatnonzero(lit)
    return 1 - rows.min() / lit.size if len(rows) else 0.0


@pytest.mark.parametrize("level,expect", [
    (0, (0, 1, 0)), (1, (3, 0, 1)), (2, (3, 2, 2)), (3, (3, 3, 3)),
])
def test_legacy_intensity_maps_to_new_knobs(level, expect):
    s = resolve_effect("flame", {"preset": "blue", "intensity": level})
    assert (s.values["brightness"], s.values["height"], s.values["activity"]) == expect
    assert s.palette == "blue"


def test_new_keys_win_over_legacy():
    s = resolve_effect("lava", {"preset": "red", "intensity": 3, "palette": "green", "height": 0})
    assert s.palette == "green"
    assert s.values["height"] == 0 and s.values["brightness"] == 3


def test_legacy_custom_stops_become_colors():
    cfg = migrate_fire_config({"preset": "blue", "core": [1, 2, 3], "ember": [9, 9, 9]})
    blue = FIRE_THEMES["blue"]
    assert cfg["colors"] == [[1, 2, 3], list(blue["mid"]), list(blue["tip"]), [9, 9, 9]]
    assert resolve_effect("flame", cfg).palette is None


def test_effect_api_and_validation():
    api = effect_config_for_api("flame", {"intensity": 2})
    keys = [o["key"] for o in api["options"]]
    assert keys == ["height", "activity", "brightness", "color_rotate_speed", "intro"]
    assert api["palette"] == "orange" and len(api["colors"]) == 4
    assert validate_effect_patch("lava", {"height": 3}) == {"height": 3}
    with pytest.raises(ValueError):
        validate_effect_patch("flame", {"intensity": 1})


@pytest.mark.parametrize("cls", [FlameMode, LavaMode])
@pytest.mark.parametrize("height,share", [(0, 1 / 3), (2, 2 / 3)])
def test_height_caps_the_fire(monkeypatch, cls, height, share):
    top = _lit_top(_mode(monkeypatch, cls, {"height": height, "activity": 3}))
    assert share * 0.75 < top <= share + 0.05


@pytest.mark.parametrize("activity", range(4))
def test_every_activity_is_visible(monkeypatch, activity):
    top = _lit_top(_mode(monkeypatch, FlameMode, {"height": 3, "activity": activity}))
    assert top > 0.8


def test_brightness_only_scales_output(monkeypatch):
    dim = _mode(monkeypatch, LavaMode, {"brightness": 0})
    bright = _mode(monkeypatch, LavaMode, {"brightness": 3})
    assert dim._max_height_px == bright._max_height_px
    assert dim._output_gain < bright._output_gain


def test_calm_runs_fewer_sim_steps(monkeypatch):
    calls = []
    mode = _mode(monkeypatch, FlameMode, {"activity": 0})
    monkeypatch.setattr(mode._sim, "update", lambda: calls.append(1))
    monkeypatch.setattr(fm, "set_pillow_image", lambda canvas, frame: None)

    class Matrix:
        def SwapOnVSync(self, canvas):
            return canvas

    for _ in range(100):
        mode.tick(Matrix(), None)
    assert len(calls) == 50


def test_natural_starts_cold_instant_starts_burning(monkeypatch):
    cold = _mode(monkeypatch, LavaMode, {"height": 3, "activity": 3})
    assert cold._sim.heat.max() == 0.0
    cold.teardown()
    fm.FireMode._handoff = None
    warm = _mode(monkeypatch, LavaMode, {"height": 3, "activity": 3, "brightness": 3, "intro": 2})
    assert np.asarray(warm._render()).mean() > 20


def test_slow_build_ramps_fuel(monkeypatch):
    mode = _mode(monkeypatch, FlameMode, {"intro": 1})
    full = mode._seed_heat
    mode._apply_intro()
    assert mode._sim.seed_heat < 0.2 * full
    mode._elapsed = SLOW_BUILD_S
    mode._apply_intro()
    mode._elapsed = SLOW_BUILD_S - mode.tick_interval
    mode._apply_intro()
    assert mode._sim.seed_heat == pytest.approx(full)


def test_settings_change_keeps_the_flames(monkeypatch):
    mode = _mode(monkeypatch, FlameMode, {"intro": 1})
    for _ in range(200):
        mode._sim.update()
    heat = mode._sim.heat.copy()
    mode.teardown()
    again = _mode(monkeypatch, FlameMode, {"intro": 1, "palette": "blue"})
    assert np.array_equal(again._sim.heat, heat)
    assert again._elapsed >= SLOW_BUILD_S


def test_switching_profiles_starts_fresh(monkeypatch):
    flame = _mode(monkeypatch, FlameMode, {})
    for _ in range(100):
        flame._sim.update()
    flame.teardown()
    lava = _mode(monkeypatch, LavaMode, {})
    assert lava._sim.heat.max() == 0.0
