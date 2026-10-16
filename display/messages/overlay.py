"""Display-loop side of custom messages: decide what is due and draw it."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from display.messages.render import build_content, compose_frame
from display.messages.schedule import current_showing
from display.messages.store import load_preview, load_state
from display.pillow_compat import set_pillow_image

# (key, message, started_at epoch, ends_at epoch)
Active = Tuple[str, Dict[str, Any], float, float]


class CustomMessageOverlay:
    def __init__(self, timezone: ZoneInfo, width: int, height: int,
                 fps: float = 10.0, scroll_pps: float = 12.0) -> None:
        self.timezone = timezone
        self.width = width
        self.height = height
        self.tick_interval = 1.0 / fps
        self.scroll_pps = scroll_pps
        self._active: Optional[Active] = None
        self._next_check = 0.0
        self._content_key: Optional[str] = None
        self._content = None

    def _lookup(self, now: float) -> Optional[Active]:
        preview = load_preview(now)
        if preview:
            msg = preview["message"]
            return (f"preview:{msg['id']}@{preview['started_at']}", msg,
                    float(preview["started_at"]), float(preview["until"]))
        messages = load_state()["messages"]
        if not messages:
            return None
        showing = current_showing(messages, datetime.fromtimestamp(now, self.timezone))
        if showing is None:
            return None
        return (showing.key, showing.message, showing.start.timestamp(), showing.end.timestamp())

    def active(self, now: Optional[float] = None) -> Optional[Active]:
        """The message to show now. Re-reads the schedule at most twice a second."""
        now = time.time() if now is None else now
        if self._active is not None and now >= self._active[3]:
            self._active = None
            self._next_check = 0.0
        if now >= self._next_check:
            self._active = self._lookup(now)
            self._next_check = now + 0.5
        return self._active

    def has_active_message(self) -> bool:
        return self.active() is not None

    def tick(self, matrix, canvas):
        current = self.active()
        if current is None:
            return canvas
        key, message, started_at, _ends_at = current
        if key != self._content_key:
            self._content = build_content(message["lines"], self.width, self.height)
            self._content_key = key
        frame = compose_frame(self._content, self.width, self.height,
                              time.time() - started_at, self.scroll_pps)
        set_pillow_image(canvas, frame)
        return matrix.SwapOnVSync(canvas)
