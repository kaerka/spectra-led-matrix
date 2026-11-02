import numpy as np
import pytest

import display.modes.starfield as sf
from display.modes.starfield_config import (
    extra_options_for_api,
    resolve_trail,
    starfield_config_for_api,
    validate_extra_option,
)


class _Canvas:
    pass


def _mode(monkeypatch, size, cfg):
    monkeypatch.setattr(sf, "CANVAS_W", size[0])
    monkeypatch.setattr(sf, "CANVAS_H", size[1])
    monkeypatch.setattr(sf, "_config_from_state", lambda: cfg)
    monkeypatch.setattr(sf, "set_pillow_image", lambda canvas, img: setattr(canvas, "img", img))
    mode = sf.StarfieldMode()
    mode.setup(None)
    return mode


class _Matrix:
    def SwapOnVSync(self, canvas):
        return canvas


@pytest.mark.parametrize("size", [(64, 64), (128, 64), (192, 192)])
@pytest.mark.parametrize("cfg", [
    {},
    {"intensity": 3, "star_size": 1, "trail": 3},
    {"intensity": 2, "color_mode": "rainbow", "color_rotate_speed": 2, "trail": 2},
    {"color_mode": "dual", "star_size": 0, "trail": 0, "color_rotate_speed": 3},
])
def test_renders(monkeypatch, size, cfg):
    mode = _mode(monkeypatch, size, cfg)
    canvas = _Canvas()
    for _ in range(60):
        mode.tick(_Matrix(), canvas)
    frame = np.asarray(canvas.img)
    assert frame.shape == (size[1], size[0], 3)
    assert frame.max() > 0


def test_fine_stars_stay_small(monkeypatch):
    mode = _mode(monkeypatch, (64, 64), {"intensity": 3, "trail": 0})
    mode._sim.x[:] = 0.3
    mode._sim.y[:] = 0.3
    mode._sim.z[:] = sf._Z_NEAR + 0.01
    frame = np.asarray(mode._render(0.0, 1.0))
    assert np.count_nonzero(frame.any(axis=2)) <= 12


def test_hyperspace_jump_cycle(monkeypatch):
    mode = _mode(monkeypatch, (64, 64), {"jumps": 2})
    mode._next_jump = 0.0
    boosts = []
    canvas = _Canvas()
    for _ in range(int(6.0 / mode.tick_interval)):
        boosts.append(mode._boost())
        mode.tick(_Matrix(), canvas)
    assert max(boosts) == pytest.approx(sf._JUMP_PEAK, rel=0.05)
    assert boosts[-1] == 1.0
    assert mode._next_jump is not None and mode._next_jump > mode._t


def test_no_jumps_when_off(monkeypatch):
    mode = _mode(monkeypatch, (64, 64), {})
    assert mode._next_jump is None
    mode._t = 1e6
    assert mode._boost() == 1.0


def test_options_api_and_validation():
    opts = {o["key"]: o for o in extra_options_for_api({"intensity": 3})}
    assert opts["star_size"]["value"] == 0
    assert opts["trail"]["value"] == resolve_trail({"intensity": 3}) == 2
    assert opts["jumps"]["value"] == 0
    assert resolve_trail({"trail": 0, "intensity": 3}) == 0
    assert "options" in starfield_config_for_api({})
    validate_extra_option("trail", 3)
    for key, bad in (("trail", 4), ("jumps", -1), ("star_size", True), ("star_size", "1")):
        with pytest.raises(ValueError):
            validate_extra_option(key, bad)
