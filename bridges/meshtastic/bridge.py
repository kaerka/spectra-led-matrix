#!/usr/bin/env python3
"""Bridge meshtasticd TCP :4403 mesh text to MQTT for matrix overlay."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import paho.mqtt.client as mqtt
from pubsub import pub


def _config_paths() -> List[Path]:
    paths: List[Path] = []
    env_path = os.environ.get("SPECTRA_MESHTASTIC_CONFIG", "").strip()
    if env_path:
        paths.append(Path(env_path))
    paths.extend(
        [
            Path("/data/spectra/config/meshtastic-bridge.local.json"),
            Path(__file__).resolve().parent / "config.local.json",
        ]
    )
    return paths


def load_config() -> Dict[str, Any]:
    for path in _config_paths():
        if path.is_file():
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
    raise SystemExit(
        "Meshtastic bridge config not found. Deploy meshtastic-bridge.local.json "
        "or set SPECTRA_MESHTASTIC_CONFIG."
    )


def extract_text(packet: dict) -> Optional[str]:
    decoded = packet.get("decoded") or {}
    text = decoded.get("text")
    if isinstance(text, str) and text.strip():
        cleaned = text.strip()
        return cleaned if _displayable(cleaned) else None

    portnum = decoded.get("portnum")
    if portnum not in (None, "TEXT_MESSAGE_APP", 1, "1"):
        return None

    payload = decoded.get("payload")
    if isinstance(payload, (bytes, bytearray)):
        text = payload.decode("utf-8", "replace").strip()
        return text if text and _displayable(text) else None
    if isinstance(payload, str) and payload.strip():
        cleaned = payload.strip()
        return cleaned if _displayable(cleaned) else None

    if portnum in ("TEXT_MESSAGE_APP", 1, "1"):
        if isinstance(text, str):
            cleaned = text.strip()
            return cleaned if cleaned and _displayable(cleaned) else None
    return None


def _displayable(text: str) -> bool:
    try:
        from display.mqtt.formatters import is_displayable_caption

        return is_displayable_caption(text)
    except ImportError:
        return bool(text.strip()) and "\ufffd" not in text


def sender_label(packet: dict, nodes: dict) -> str:
    from_id = packet.get("fromId") or packet.get("from")
    if not from_id:
        return "MESH"
    node = nodes.get(from_id) or {}
    user = node.get("user") or {}
    short = user.get("shortName") or user.get("longName")
    if short:
        return str(short)
    return str(from_id)[-4:]


class MeshtasticMqttBridge:
    def __init__(self, cfg: Dict[str, Any]) -> None:
        self.cfg = cfg
        self.host = str(cfg.get("meshtasticd_host", "localhost"))
        self.port = int(cfg.get("meshtasticd_port", 4403))
        self.connect_timeout = int(cfg.get("connect_timeout", 15))
        self.retry_seconds = float(cfg.get("retry_seconds", 30))
        self.topic = str(cfg.get("topic", "meshtastic/message"))
        self.ttl = int(cfg.get("mqtt_ttl", 30))
        self.color = cfg.get("text_color", [0, 200, 255])
        self.prefix_sender = bool(cfg.get("prefix_sender", True))

        self.mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt.connect(str(cfg.get("broker", "127.0.0.1")), int(cfg.get("port", 1883)), 60)
        self.mqtt.loop_start()

        self._iface = None
        self._nodes: dict = {}

    def publish_text(self, text: str) -> None:
        payload = json.dumps({"text": text, "ttl": self.ttl, "color": self.color})
        self.mqtt.publish(self.topic, payload, qos=0)
        preview = text if len(text) <= 120 else text[:117] + "..."
        print(f"MQTT {self.topic}: {preview}", flush=True)

    def on_receive(self, packet: dict, interface) -> None:  # noqa: ANN001
        text = extract_text(packet)
        if not text:
            return
        if self.prefix_sender:
            nodes = getattr(interface, "nodes", None) or self._nodes
            label = sender_label(packet, nodes)
            text = f"{label}: {text}"
        self.publish_text(text)

    def run(self) -> None:
        pub.subscribe(self.on_receive, "meshtastic.receive")

        while True:
            try:
                from meshtastic.tcp_interface import TCPInterface

                print(
                    f"Connecting meshtasticd at {self.host}:{self.port}...",
                    flush=True,
                )
                iface = TCPInterface(
                    hostname=self.host,
                    portNumber=self.port,
                    connectNow=True,
                    timeout=self.connect_timeout,
                )
                self._iface = iface
                self._nodes = iface.nodes or {}
                print("Meshtastic connected; forwarding mesh text to MQTT", flush=True)

                while iface.isConnected.is_set():
                    if iface.nodes:
                        self._nodes = iface.nodes
                    time.sleep(1)
                raise RuntimeError("Meshtastic connection lost")
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print(f"Reconnect in {self.retry_seconds:.0f}s: {exc}", flush=True)
                if self._iface:
                    try:
                        self._iface.close()
                    except Exception:
                        pass
                    self._iface = None
                time.sleep(self.retry_seconds)


def main() -> None:
    bridge = MeshtasticMqttBridge(load_config())
    bridge.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
