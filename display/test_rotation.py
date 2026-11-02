import random

import pytest

from display import rotation
from display.rotation import (
    Rotator,
    load_rotation,
    next_switch_at,
    rotation_for_api,
    update_rotation,
)
from display.state import DisplayState


@pytest.fixture
def path(tmp_path):
    return str(tmp_path / "rotation.json")


def _state(mode="plasma", updated_at=1000.0):
    s = DisplayState()
    s.active_mode = mode
    s.updated_at = updated_at
    return s


def test_defaults_when_missing(path):
    s = load_rotation(path)
    assert s.enabled is False
    assert s.interval_s == rotation.DEFAULT_INTERVAL
    assert "media" not in s.modes
    assert "weather" not in s.modes
    assert len(s.pool()) >= 2


@pytest.mark.parametrize(
    "patch",
    [
        {},
        {"enabled": "yes"},
        {"interval_s": 7},
        {"modes": ["plasma"]},
        {"modes": ["plasma", "plasma"]},
        {"modes": ["plasma", "media"]},
        {"modes": ["plasma", "nope"]},
        {"bogus": 1},
    ],
)
def test_update_rejects_bad_input(path, patch):
    with pytest.raises(ValueError):
        update_rotation(patch, path)


def test_update_persists(path):
    update_rotation({"enabled": True, "interval_s": 60, "modes": ["dvd", "plasma"]}, path)
    s = load_rotation(path)
    assert s.enabled and s.interval_s == 60
    assert sorted(s.modes) == ["dvd", "plasma"]
    assert s.updated_at > 0


def test_countdown_restarts_on_latest_change(path):
    s = update_rotation({"enabled": True, "interval_s": 300}, path)
    s.updated_at = 500.0
    assert next_switch_at(s, _state(updated_at=1000.0)) == 1300.0
    s.updated_at = 2000.0
    assert next_switch_at(s, _state(updated_at=1000.0)) == 2300.0
    s.enabled = False
    assert next_switch_at(s, _state()) is None


def test_api_payload(path):
    update_rotation({"enabled": True}, path)
    data = rotation_for_api(_state(), path)
    assert data["enabled"] is True
    assert {i["seconds"] for i in data["intervals"]} == set(rotation.INTERVALS)
    assert all(m["id"] != "media" for m in data["available"])
    assert data["seconds_left"] is not None


def test_rotator_waits_then_switches(path, monkeypatch):
    picked = []
    monkeypatch.setattr(rotation, "set_active_mode", lambda m: picked.append(m))
    update_rotation({"enabled": True, "interval_s": 60, "modes": ["dvd", "plasma", "pong"]}, path)
    s = load_rotation(path)
    state = _state("plasma", updated_at=s.updated_at)
    r = Rotator(path, random.Random(1))
    assert r.maybe_rotate(state, now=s.updated_at + 30) is None
    pick = r.maybe_rotate(state, now=s.updated_at + 61)
    assert pick in {"dvd", "pong"}
    assert picked == [pick]


def test_rotator_never_repeats_current(path, monkeypatch):
    monkeypatch.setattr(rotation, "set_active_mode", lambda m: None)
    update_rotation({"enabled": True, "modes": ["dvd", "plasma"]}, path)
    r = Rotator(path, random.Random(0))
    current = "plasma"
    for _ in range(20):
        nxt = r.maybe_rotate(_state(current, updated_at=0.0), now=1e12)
        assert nxt != current
        current = nxt
