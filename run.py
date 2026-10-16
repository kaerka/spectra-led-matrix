#!/usr/bin/env python3
"""
Spectra matrix display — web control + display runner.

Starts FastAPI (port 8080) in the main thread. The matrix display loop runs in
a child process so video-viewer can take GPIO when playing MP4s (the Python
rgbmatrix bindings cannot release /dev/mem in-process).

Usage:
    export PYTHONPATH=~/spectra-led-matrix/rpi-rgb-led-matrix/bindings/python
    sudo -E env PYTHONPATH=$PYTHONPATH .venv/bin/python run.py

Environment:
    MATRIX_WEB_HOST  (default 0.0.0.0)
    MATRIX_WEB_PORT  (default 8080)
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time

import uvicorn

from display.video_handoff import (
    VIDEO_HANDOFF_EXIT,
    kill_video_viewer,
    run_video_player_subprocess,
)
from display.media_video import should_hand_off_to_video
from web.app import app

WORKER_SCRIPT = os.path.join(os.path.dirname(__file__), "run_display_worker.py")


def _worker_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def _start_web_server() -> None:
    host = os.environ.get("MATRIX_WEB_HOST", "0.0.0.0")
    port = int(os.environ.get("MATRIX_WEB_PORT", "8080"))
    uvicorn.run(app, host=host, port=port, log_level="info")


def _supervise_display() -> None:
    python = sys.executable
    while True:
        proc = subprocess.Popen([python, WORKER_SCRIPT], env=_worker_env())
        rc = proc.wait()

        if rc == VIDEO_HANDOFF_EXIT:
            handoff, path = should_hand_off_to_video()
            if path:
                time.sleep(3.0)
                run_video_player_subprocess(path)
            continue

        if rc != 0:
            print(f"[display] worker exited rc={rc}; restarting in 2s", flush=True)
            time.sleep(2)


def main() -> None:
    if os.geteuid() != 0:
        print("Warning: matrix GPIO usually requires root (sudo).", file=sys.stderr)

    def _shutdown(_signum, _frame) -> None:
        kill_video_viewer()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    supervisor = threading.Thread(
        target=_supervise_display, name="display-supervisor", daemon=True
    )
    supervisor.start()
    print(
        f"Web UI: http://{os.environ.get('MATRIX_WEB_HOST', '0.0.0.0')}:"
        f"{os.environ.get('MATRIX_WEB_PORT', '8080')}/",
        flush=True,
    )

    _start_web_server()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
