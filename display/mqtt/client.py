"""MQTT payload parsing and client wiring."""

from __future__ import annotations

import json
import threading
from typing import Any, Callable, Dict, Optional, Tuple

from display.mqtt.formatters import is_displayable_caption


class MessageState:
    """Latest message, shared between the MQTT thread and the display loop."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.text: Optional[str] = None
        self.color: Tuple[int, int, int] = (255, 255, 255)
        self.ttl = 30.0
        self.arrived = 0.0
        self.version = 0
        self.connected = False
        self.topic: Optional[str] = None

    def update(
        self,
        text: str,
        color: Tuple[int, int, int],
        ttl: float,
        topic: Optional[str] = None,
    ) -> None:
        import time

        with self.lock:
            self.text = text
            self.color = color
            self.ttl = ttl
            self.arrived = time.time()
            self.version += 1
            self.topic = topic

    def snapshot(self):
        import time

        with self.lock:
            return (
                self.version,
                self.text,
                self.color,
                self.ttl,
                self.arrived,
                self.connected,
                self.topic,
            )

    def is_active(self) -> bool:
        import time

        with self.lock:
            if self.text is None:
                return False
            return (time.time() - self.arrived) < self.ttl


def parse_payload(
    payload: bytes,
    cfg: Dict[str, Any],
    *,
    text_extractor: Optional[Callable[[str, str], Optional[str]]] = None,
) -> Tuple[str, float, Tuple[int, int, int]]:
    """Return (text, ttl, color). Accepts plain text or JSON."""
    raw = payload.decode("utf-8", "replace").strip()
    text = raw
    ttl = float(cfg["idle_seconds"])
    color = tuple(cfg["text_color"])
    topic = cfg.get("_topic", "")

    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        obj = None

    if isinstance(obj, dict):
        if text_extractor:
            extracted = text_extractor(raw, topic)
            if extracted:
                text = extracted.strip()
            else:
                text = str(obj.get("text", obj.get("message", ""))).strip()
        else:
            text = str(obj.get("text", obj.get("message", ""))).strip()
        if "ttl" in obj:
            try:
                ttl = float(obj["ttl"])
            except (ValueError, TypeError):
                pass
        c = obj.get("color")
        if isinstance(c, (list, tuple)) and len(c) == 3:
            try:
                color = tuple(max(0, min(255, int(v))) for v in c)
            except (ValueError, TypeError):
                pass
    elif isinstance(obj, str):
        text = obj.strip()

    return text, ttl, color


def make_client(
    cfg: Dict[str, Any],
    state: MessageState,
    text_extractor=None,
    *,
    accept_topic: Optional[Callable[[str], bool]] = None,
):
    import paho.mqtt.client as mqtt

    try:
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION1,
            client_id=cfg["client_id"],
            clean_session=True,
        )
    except (AttributeError, TypeError):
        client = mqtt.Client(client_id=cfg["client_id"], clean_session=True)

    if cfg.get("username"):
        client.username_pw_set(cfg["username"], cfg.get("password"))
    if cfg.get("tls"):
        client.tls_set()

    def on_connect(c, _u, _flags, rc, *_):
        with state.lock:
            state.connected = rc == 0
        for topic in cfg["topics"]:
            c.subscribe(topic)
        print(f"[mqtt] connected rc={rc} -> subscribed {cfg['topics']}", flush=True)

    def on_disconnect(_c, _u, rc, *_):
        with state.lock:
            state.connected = False
        print(f"[mqtt] disconnected rc={rc}", flush=True)

    def on_message(_c, _u, msg):
        if accept_topic is not None and not accept_topic(msg.topic):
            return
        parse_cfg = dict(cfg)
        parse_cfg["_topic"] = msg.topic
        text, ttl, color = parse_payload(
            msg.payload, parse_cfg, text_extractor=text_extractor
        )
        if not text or not is_displayable_caption(text):
            return
        state.update(text, color, ttl, topic=msg.topic)
        print(f"[mqtt] {msg.topic}: {text!r} (ttl={ttl}s)", flush=True)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.connect_async(cfg["broker"], int(cfg["port"]), keepalive=60)
    return client
