"""Main display loop — reads persisted mode and delegates rendering."""

from __future__ import annotations

import json
import sys
import traceback
import time

from display.brightness import BrightnessSchedule
from display.matrix import CANVAS_H, CANVAS_W, build_matrix
from display.messages.overlay import CustomMessageOverlay
from display.modes.media import MediaMode
from display.modes.registry import create_mode
from display.mqtt.overlay import MqttOverlay
from display.state import DEFAULT_MODE, load_state
from display.video_handoff import VIDEO_HANDOFF_EXIT


def _state_key(state) -> tuple:
    cfg = None
    if state.mode_config and state.active_mode:
        raw = state.mode_config.get(state.active_mode)
        if raw:
            cfg = json.dumps(raw, sort_keys=True)
    return (state.active_mode or DEFAULT_MODE, state.media_path, cfg)


def _teardown_mode(mode):
    if mode is not None:
        try:
            mode.teardown()
        except Exception:
            traceback.print_exc()
    return None


def _ensure_matrix(matrix, canvas, schedule: BrightnessSchedule):
    """Create matrix/canvas once; reuse canvas across ticks (hzeller double-buffer).

    Do not call CreateFrameCanvas() every frame — that leaks until process exit.
    """
    if matrix is None:
        matrix = build_matrix(brightness=schedule.initial_brightness())
        canvas = matrix.CreateFrameCanvas()
    else:
        schedule.apply_if_needed(matrix)
        if canvas is None:
            canvas = matrix.CreateFrameCanvas()
    return matrix, canvas


def _release_matrix(matrix):
    if matrix is None:
        return None, None
    try:
        matrix.Clear()
    except Exception:
        pass
    try:
        del matrix
    except Exception:
        pass
    import gc

    gc.collect()
    time.sleep(0.5)
    return None, None


def run_display_loop() -> None:
    matrix = None
    canvas = None
    active_key = None
    mode = None
    schedule = BrightnessSchedule.load_from_config()
    mqtt = MqttOverlay.load_from_config()
    mqtt.start()
    messages = CustomMessageOverlay(schedule.timezone, CANVAS_W, CANVAS_H)

    print("Display runner started. Switch modes via the web UI.", flush=True)
    if schedule.enabled:
        print(
            f"Night dim enabled ({schedule.timezone.key}): "
            f"currently {schedule.initial_brightness()}%",
            flush=True,
        )

    while True:
        try:
            if schedule.apply_if_needed(matrix):
                pass

            if mqtt.has_active_message():
                matrix, canvas = _ensure_matrix(matrix, canvas, schedule)
                canvas = mqtt.tick(matrix, canvas)
                time.sleep(max(mqtt.tick_interval(), 0.02))
                continue

            if messages.has_active_message():
                matrix, canvas = _ensure_matrix(matrix, canvas, schedule)
                canvas = messages.tick(matrix, canvas)
                time.sleep(messages.tick_interval)
                continue

            state = load_state()
            key = _state_key(state)

            if key != active_key:
                mode = _teardown_mode(mode)
                mode_id = key[0]
                print(f"Switching display: mode={mode_id!r} media={key[1]!r}", flush=True)
                mode = create_mode(mode_id)

                if isinstance(mode, MediaMode) and mode.uses_external_player():
                    matrix, canvas = _release_matrix(matrix)
                    print("[display] handing off MP4 to parent video-viewer", flush=True)
                    sys.exit(VIDEO_HANDOFF_EXIT)

                matrix, canvas = _ensure_matrix(matrix, canvas, schedule)
                mode.setup(matrix)
                active_key = key

            if mode is None:
                matrix, canvas = _ensure_matrix(matrix, canvas, schedule)
                mode = create_mode(key[0])
                active_key = key
                if isinstance(mode, MediaMode) and mode.uses_external_player():
                    matrix, canvas = _release_matrix(matrix)
                    print("[display] handing off MP4 to parent video-viewer", flush=True)
                    sys.exit(VIDEO_HANDOFF_EXIT)
                mode.setup(matrix)

            canvas = mode.tick(matrix, canvas)
            time.sleep(getattr(mode, "tick_interval", 0.15))
        except Exception:
            print("Display loop error:", flush=True)
            traceback.print_exc()
            mode = _teardown_mode(mode)
            mode = None
            active_key = None
            time.sleep(1.0)
