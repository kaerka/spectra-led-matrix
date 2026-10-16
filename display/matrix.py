"""Build the RGBMatrix from the per-device config (display/matrix_config.py)."""

import os

from rgbmatrix import RGBMatrix, RGBMatrixOptions

from display.matrix_config import CANVAS_H, CANVAS_W, DATA_ROOT, MATRIX
from display.video_viewer_cli import resolve_video_viewer_bin, video_viewer_command

__all__ = ["CANVAS_H", "CANVAS_W", "MATRIX", "VIDEO_VIEWER_BIN", "build_matrix",
           "video_viewer_command"]

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
VIDEO_VIEWER_BIN = resolve_video_viewer_bin() or os.path.join(
    DATA_ROOT, "repos", "rpi-rgb-led-matrix", "utils", "video-viewer"
)


def build_matrix(*, brightness: int = 100, show_refresh_rate: bool = False) -> RGBMatrix:
    options = RGBMatrixOptions()
    options.rows = MATRIX.panel_rows
    options.cols = MATRIX.panel_cols
    options.chain_length = MATRIX.chain_length
    options.parallel = MATRIX.parallel
    options.hardware_mapping = MATRIX.hardware_mapping
    options.pixel_mapper_config = MATRIX.pixel_mapper
    options.gpio_slowdown = MATRIX.gpio_slowdown
    options.pwm_bits = MATRIX.pwm_bits
    options.pwm_lsb_nanoseconds = MATRIX.pwm_lsb_nanoseconds
    options.brightness = MATRIX.clamp_brightness(brightness)
    options.limit_refresh_rate_hz = MATRIX.limit_refresh_hz
    options.show_refresh_rate = show_refresh_rate
    options.drop_privileges = False
    return RGBMatrix(options=options)
