"""Parent-process video playback helpers (no rgbmatrix imports)."""

from __future__ import annotations

import os
import subprocess
import sys

from display.media_video import should_hand_off_to_video

VIDEO_HANDOFF_EXIT = 75

VIDEO_PLAYER_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "run_video_player.py"
)


def kill_video_viewer() -> None:
    try:
        subprocess.run(
            ["pkill", "-f", "video-viewer"],
            timeout=3,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def run_video_player_subprocess(path: str) -> bool:
    """Run isolated video player process. Returns True if playback likely succeeded."""
    proc = subprocess.Popen(
        [sys.executable, VIDEO_PLAYER_SCRIPT, path],
        env=os.environ.copy(),
    )
    return proc.wait() == 0
