import numpy as np

import display.modes.gibson as gibson
from display.rotation import rotatable_modes


def test_renders_small_canvas(monkeypatch):
    monkeypatch.setattr(gibson, "CANVAS_W", 48)
    monkeypatch.setattr(gibson, "CANVAS_H", 32)
    monkeypatch.setattr(gibson, "_config_from_state", lambda: None)
    mode = gibson.GibsonMode()
    mode.setup(None)
    for _ in range(3):
        mode._update_camera()
        mode._maybe_state_update()
        frame = np.asarray(mode._render())
    assert frame.shape == (32, 48, 3)
    assert frame.any()


def test_not_in_auto_rotate():
    assert "gibson" not in rotatable_modes()
