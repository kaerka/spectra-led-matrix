"""Clear retained MQTT messages on the broker.

A retained caption is replayed to every wall each time it reconnects (service
restart, network blip), so an old message can keep coming back.
"""

from __future__ import annotations

import threading
import time
from typing import List, Sequence

import paho.mqtt.client as mqtt

# Retained on purpose: small boards read their message schedule from here.
KEEP_PREFIXES = ("spectra/messages/",)


def clear_retained(broker: str, port: int, keep_prefixes: Sequence[str] = KEEP_PREFIXES,
                   listen_seconds: float = 1.5) -> List[str]:
    """Empty every retained topic except ``keep_prefixes``; returns the topics cleared."""
    found: List[str] = []
    lock = threading.Lock()

    def on_message(_client, _userdata, msg):
        if msg.retain and msg.payload and not msg.topic.startswith(tuple(keep_prefixes)):
            with lock:
                if msg.topic not in found:
                    found.append(msg.topic)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = on_message
    client.connect(broker, port, 30)
    client.loop_start()
    try:
        client.subscribe("#", qos=0)
        # Retained messages arrive right after SUBACK; a short wait catches them.
        time.sleep(listen_seconds)
        client.unsubscribe("#")
        with lock:
            topics = list(found)
        for topic in topics:
            client.publish(topic, b"", qos=1, retain=True).wait_for_publish(timeout=3.0)
    finally:
        client.loop_stop()
        client.disconnect()
    return topics
