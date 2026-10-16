#!/usr/bin/env python3
"""Play one MP4 via video-viewer — isolated process with no rgbmatrix import."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

from display.state import load_state
from display.video_viewer_cli import video_viewer_command


def _stop(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception:
        proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=2)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: run_video_player.py <video-path>", file=sys.stderr)
        return 2
    path = sys.argv[1]
    watched = (load_state().active_mode, path)
    cmd = video_viewer_command(path)
    print(f"[video] starting: {path}", flush=True)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid,
    )
    started = time.monotonic()
    try:
        while proc.poll() is None:
            state = load_state()
            current = (state.active_mode, state.media_path)
            if current != watched:
                print(f"[video] state changed {watched!r} -> {current!r}", flush=True)
                break
            time.sleep(0.4)
    finally:
        _stop(proc)

    if proc.returncode not in (None, 0) and proc.stderr:
        err = proc.stderr.read().decode("utf-8", "replace").strip()
        if err:
            print(f"[video] exited rc={proc.returncode}: {err}", flush=True)

    return 0 if (proc.returncode == 0 or time.monotonic() - started > 3.0) else 1


if __name__ == "__main__":
    sys.exit(main())
