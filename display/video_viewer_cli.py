"""Build hzeller video-viewer argv without importing rgbmatrix (safe for parent process)."""

from __future__ import annotations

import os

from display.matrix_config import DATA_ROOT, MATRIX


def resolve_video_viewer_bin() -> str | None:
    repo_root = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..")
    )
    candidates = [
        os.path.join(DATA_ROOT, "repos", "rpi-rgb-led-matrix", "utils", "video-viewer"),
        os.path.join(repo_root, "rpi-rgb-led-matrix", "utils", "video-viewer"),
    ]
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def video_viewer_command(path: str, *, brightness: int | None = None) -> list[str]:
    if brightness is None:
        try:
            from display.brightness import scheduled_brightness

            brightness = scheduled_brightness()
        except Exception:
            brightness = MATRIX.max_brightness
    viewer = resolve_video_viewer_bin()
    if not viewer:
        raise FileNotFoundError("video-viewer binary not found")
    argv = [
        viewer,
        f"--led-slowdown-gpio={MATRIX.video.gpio_slowdown}",
        f"--led-chain={MATRIX.chain_length}",
        f"--led-parallel={MATRIX.parallel}",
        f"--led-rows={MATRIX.panel_rows}",
        f"--led-cols={MATRIX.panel_cols}",
        f"--led-gpio-mapping={MATRIX.hardware_mapping}",
        f"--led-brightness={MATRIX.clamp_brightness(brightness)}",
        f"--led-pwm-bits={MATRIX.video.pwm_bits}",
        f"--led-pwm-lsb-nanoseconds={MATRIX.pwm_lsb_nanoseconds}",
    ]
    if MATRIX.pixel_mapper:
        argv += ["--led-pixel-mapper", MATRIX.pixel_mapper]
    return argv + [
        f"--led-scan-mode={MATRIX.video.scan_mode}",
        "-T",
        "4",
        "-F",
        "-f",
        path,
    ]
