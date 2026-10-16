"""Full-screen GIF/MP4 playback.

GIFs play in-process (Pillow). MP4 and other video files are handed off to the
parent process (``run.py``) which runs hzeller ``video-viewer`` in an isolated
child after the display worker exits.
"""

from __future__ import annotations

import time

from PIL import Image, ImageSequence
from rgbmatrix import RGBMatrix

from display.matrix import CANVAS_H, CANVAS_W
from display.media_library import resolve_media_path
from display.media_video import uses_external_player
from display.pillow_compat import set_pillow_image
from display.state import load_state


class MediaMode:
    tick_interval = 0.01

    def __init__(self) -> None:
        self._gif_path: str | None = None
        self._gif: Image.Image | None = None
        self._gif_iter = None
        self._frame_delay = 1.0 / 24.0
        self._next_at = 0.0
        self._last_frame: Image.Image | None = None

    def uses_external_player(self, path: str | None = None) -> bool:
        return uses_external_player(path)

    def setup(self, matrix: RGBMatrix) -> None:
        path = resolve_media_path(load_state().media_path)
        if not path:
            raise RuntimeError(
                "No media files found in ~/matrix-gif-animations or ~/matrix-mp4-animations"
            )
        if self.uses_external_player(path):
            raise RuntimeError(
                "Video playback must be handed off to the parent process "
                f"(unexpected setup for {path})"
            )
        self._open_gif(path)

    def teardown(self) -> None:
        if self._gif:
            self._gif.close()
        self._gif = None
        self._gif_iter = None
        self._gif_path = None
        self._last_frame = None

    def _open_gif(self, path: str) -> None:
        if self._gif:
            self._gif.close()
        self._gif_path = path
        self._gif = Image.open(path)
        self._gif_iter = ImageSequence.Iterator(self._gif)
        delay_ms = self._gif.info.get("duration", 42)
        self._frame_delay = max(delay_ms / 1000.0, 1.0 / 30.0)
        self._next_at = 0.0
        self._last_frame = None
        print(f"Media mode (gif): {path}", flush=True)

    def _gif_seconds_until_next(self) -> float:
        return max(0.0, self._next_at - time.monotonic())

    def _next_gif_frame(self) -> Image.Image | None:
        now = time.monotonic()
        if now < self._next_at:
            return None
        self._next_at = now + self._frame_delay
        assert self._gif_iter is not None
        try:
            frame = next(self._gif_iter)
        except StopIteration:
            self._gif_iter = ImageSequence.Iterator(self._gif)
            frame = next(self._gif_iter)
        frame = frame.convert("RGB")
        if frame.size != (CANVAS_W, CANVAS_H):
            frame = frame.resize((CANVAS_W, CANVAS_H), Image.LANCZOS)
        return frame

    def tick(self, matrix: RGBMatrix, canvas):
        frame = self._next_gif_frame()
        if frame is None:
            if self._last_frame is None:
                return canvas
            wait = self._gif_seconds_until_next()
            if wait > 0.002:
                time.sleep(wait)
            return canvas

        self._last_frame = frame
        set_pillow_image(canvas, frame)
        return matrix.SwapOnVSync(canvas)
