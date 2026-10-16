"""Background MQTT subscriber; overlays messages on the matrix when active."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from display.matrix import CANVAS_H, CANVAS_W
from display.mqtt.client import MessageState, make_client
from display.mqtt.settings import load_overlay_settings
from display.mqtt.sources import accept_topic as topic_accepted
from display.mqtt.formatters import extract_display_text
from display.mqtt.purge import purged_at
from display.mqtt.render import (
    build_message_image,
    message_font,
    render_message_frame,
    scaled_font_size,
)
from display.pillow_compat import set_pillow_image

DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "broker": "localhost",
    "port": 1883,
    "username": None,
    "password": None,
    "tls": False,
    "topics": [
        "whisper/transcript",
        "meshtastic/message",
        "aether/#",
        "iris/#",
        "nightglass/#",
    ],
    "client_id": "spectra-matrix-controller",
    "idle_seconds": 30,
    "text_color": [255, 255, 255],
    "text_font_size": 18,
    "fps": 15,
    "scroll_px_per_sec": 18,
    "max_text_chars": 400,
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _config_paths() -> list[Path]:
    data_root = os.environ.get("SPECTRA_DATA_ROOT", "/data/spectra")
    root = _repo_root()
    return [
        Path(data_root) / "config" / "mqtt.local.json",
        root / "config" / "mqtt.local.json",
        root / "config" / "mqtt.example.json",
    ]


def load_mqtt_config() -> Dict[str, Any]:
    for path in _config_paths():
        if path.is_file():
            with path.open(encoding="utf-8") as fp:
                user = json.load(fp)
            cfg = dict(DEFAULTS)
            cfg.update(user)
            return cfg
    return dict(DEFAULTS)


class MqttOverlay:
    def __init__(self, cfg: Optional[Dict[str, Any]] = None) -> None:
        self.cfg = cfg if cfg is not None else load_mqtt_config()
        self.state = MessageState()
        self._client = None
        self._cached_ver = -1
        self._tall = None
        base_size = int(self.cfg.get("text_font_size", 18))
        size = scaled_font_size(base_size, CANVAS_W, CANVAS_H)
        self._font = message_font(size)
        self._frame_dt = 1.0 / float(self.cfg.get("fps", 20))
        # Same lines per second at any size.
        self._scroll_pps = float(self.cfg.get("scroll_px_per_sec", 18)) * size / base_size
        self._last_tick = 0.0

    @classmethod
    def load_from_config(cls) -> "MqttOverlay":
        return cls(load_mqtt_config())

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("enabled", True))

    def start(self) -> None:
        if not self.enabled:
            print("[mqtt] overlay disabled in config", flush=True)
            return
        if self._client is not None:
            return
        try:
            subscribed = list(self.cfg.get("topics") or [])

            def _accept(topic: str) -> bool:
                settings = load_overlay_settings(subscribed)
                return topic_accepted(
                    topic,
                    overlay_enabled=settings.overlay_enabled,
                    source_enabled=settings.sources,
                    subscribed_topics=subscribed,
                )

            self._client = make_client(
                self.cfg,
                self.state,
                text_extractor=extract_display_text,
                accept_topic=_accept,
            )
            self._client.loop_start()
        except Exception as exc:
            print(f"[mqtt] overlay unavailable: {exc}", flush=True)
            self.cfg = dict(self.cfg)
            self.cfg["enabled"] = False
            self._client = None
            return
        print(
            f"[mqtt] overlay started broker={self.cfg['broker']}:{self.cfg['port']}",
            flush=True,
        )

    def stop(self) -> None:
        if self._client is not None:
            self._client.loop_stop()
            self._client = None

    def has_active_message(self) -> bool:
        if not self.enabled:
            return False
        subscribed = list(self.cfg.get("topics") or [])
        settings = load_overlay_settings(subscribed)
        if not settings.overlay_enabled:
            return False
        if not self.state.is_active():
            return False
        _ver, _text, _color, _ttl, arrived, _conn, topic = self.state.snapshot()
        if arrived <= purged_at():
            return False
        if topic and not topic_accepted(
            topic,
            overlay_enabled=True,
            source_enabled=settings.sources,
            subscribed_topics=subscribed,
        ):
            return False
        return True

    def tick_interval(self) -> float:
        return self._frame_dt if self.has_active_message() else 0.0

    def tick(self, matrix, canvas):
        now = time.time()
        version, text, color, _ttl, arrived, _conn, _topic = self.state.snapshot()
        if version != self._cached_ver:
            cap = int(self.cfg.get("max_text_chars", 400))
            body = text or ""
            if cap > 0 and len(body) > cap:
                body = body[: cap - 1].rstrip() + "…"
            self._tall = build_message_image(
                body,
                self._font,
                color,
                CANVAS_W - 2,
            )
            self._cached_ver = version
        frame = render_message_frame(
            self._tall,
            now - arrived,
            self._scroll_pps,
        )
        set_pillow_image(canvas, frame)
        self._last_tick = now
        return matrix.SwapOnVSync(canvas)
