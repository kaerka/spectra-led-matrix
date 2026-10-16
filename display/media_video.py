"""Detect whether media mode should use external video-viewer."""

from __future__ import annotations

from display.media_library import resolve_media_path
from display.state import load_state
from display.video_viewer_cli import resolve_video_viewer_bin


def uses_external_player(path: str | None = None) -> bool:
    from display.state import load_state as _load

    resolved = path or resolve_media_path(_load().media_path)
    if not resolved or resolved.lower().endswith(".gif"):
        return False
    return resolve_video_viewer_bin() is not None


def should_hand_off_to_video() -> tuple[bool, str | None]:
    state = load_state()
    if state.active_mode != "media":
        return False, None
    path = resolve_media_path(state.media_path)
    if not path or not uses_external_player(path):
        return False, None
    return True, path
