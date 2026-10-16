"""Tests for MQTT source routing."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_sources_path = Path(__file__).with_name("sources.py")
_spec = importlib.util.spec_from_file_location("mqtt_sources_test", _sources_path)
assert _spec and _spec.loader
_sources = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sources)

SOURCE_CATALOG = _sources.SOURCE_CATALOG
accept_topic = _sources.accept_topic
source_for_topic = _sources.source_for_topic
topic_matches = _sources.topic_matches
topics_for_sources = _sources.topics_for_sources
wall_source_ids = _sources.wall_source_ids


class TopicMatchTests(unittest.TestCase):
    def test_exact(self) -> None:
        self.assertTrue(topic_matches("whisper/transcript", "whisper/transcript"))
        self.assertFalse(topic_matches("whisper/transcript", "meshtastic/message"))

    def test_hash_wildcard(self) -> None:
        self.assertTrue(topic_matches("custom/#", "custom/status"))
        self.assertTrue(topic_matches("custom/#", "custom/message"))
        self.assertFalse(topic_matches("custom/#", "other/status"))

    def test_source_for_topic(self) -> None:
        self.assertEqual(source_for_topic("meshtastic/message"), "meshtastic")
        self.assertEqual(source_for_topic("custom/test"), "custom")


class WallSourcesTests(unittest.TestCase):
    def test_wall_subset(self) -> None:
        ids = wall_source_ids(["meshtastic/message", "custom/#"])
        self.assertEqual(ids, ["meshtastic", "custom"])

    def test_topics_for_sources(self) -> None:
        topics = topics_for_sources(["meshtastic", "custom"])
        self.assertIn("meshtastic/message", topics)
        self.assertIn("custom/#", topics)


class AcceptTopicTests(unittest.TestCase):
    def test_overlay_disabled(self) -> None:
        self.assertFalse(
            accept_topic(
                "meshtastic/message",
                overlay_enabled=False,
                source_enabled={"meshtastic": True},
                subscribed_topics=["meshtastic/message"],
            )
        )

    def test_source_disabled(self) -> None:
        self.assertFalse(
            accept_topic(
                "meshtastic/message",
                overlay_enabled=True,
                source_enabled={"meshtastic": False},
                subscribed_topics=["meshtastic/message"],
            )
        )

    def test_allowed(self) -> None:
        self.assertTrue(
            accept_topic(
                "custom/status",
                overlay_enabled=True,
                source_enabled={"custom": True, "meshtastic": False},
                subscribed_topics=["custom/#", "meshtastic/message"],
            )
        )


if __name__ == "__main__":
    unittest.main()
