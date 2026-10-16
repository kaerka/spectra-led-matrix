"""MQTT source catalog — maps caption feeds to topic patterns."""

from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Optional

# id → label + subscription patterns (used for per-wall routing and UI toggles).
# Add your own ids here (or via inventory mqtt_source_defs) for home-automation feeds.
SOURCE_CATALOG: Dict[str, Dict[str, object]] = {
    "whisper": {
        "label": "Whisper",
        "topics": ["whisper/transcript"],
    },
    "meshtastic": {
        "label": "Meshtastic",
        "topics": ["meshtastic/message"],
    },
    "custom": {
        "label": "Custom",
        "topics": ["custom/#"],
    },
}


def topic_matches(pattern: str, topic: str) -> bool:
    """MQTT topic filter match (# multi-level, + single-level)."""
    pat = pattern.split("/")
    parts = topic.split("/")
    for i, token in enumerate(pat):
        if token == "#":
            return True
        if i >= len(parts):
            return False
        if token != "+" and token != parts[i]:
            return False
    return len(pat) == len(parts)


def source_for_topic(topic: str, catalog: Optional[Mapping[str, Dict[str, object]]] = None) -> Optional[str]:
    """Return source id whose patterns match topic, or None."""
    cat = catalog or SOURCE_CATALOG
    for source_id, meta in cat.items():
        for pattern in meta.get("topics") or ():
            if topic_matches(str(pattern), topic):
                return source_id
    return None


def topics_for_sources(
    source_ids: Iterable[str],
    catalog: Optional[Mapping[str, Dict[str, object]]] = None,
) -> List[str]:
    """Union of MQTT subscribe patterns for the given source ids."""
    cat = catalog or SOURCE_CATALOG
    seen: List[str] = []
    for source_id in source_ids:
        meta = cat.get(source_id)
        if not meta:
            continue
        for pattern in meta.get("topics") or ():
            p = str(pattern)
            if p not in seen:
                seen.append(p)
    return seen


def wall_source_ids(subscribed_topics: Iterable[str]) -> List[str]:
    """Source ids available on this wall from its mqtt.local.json topics list."""
    topics = [str(t) for t in subscribed_topics]
    found: List[str] = []
    for source_id, meta in SOURCE_CATALOG.items():
        for pattern in meta.get("topics") or ():
            p = str(pattern)
            if p in topics or any(topic_matches(p, t) for t in topics):
                if source_id not in found:
                    found.append(source_id)
                break
    return found


def accept_topic(
    topic: str,
    *,
    overlay_enabled: bool,
    source_enabled: Mapping[str, bool],
    subscribed_topics: Iterable[str],
) -> bool:
    if not overlay_enabled:
        return False
    source_id = source_for_topic(topic)
    if source_id is None:
        return False
    if not source_enabled.get(source_id, True):
        return False
    for pattern in subscribed_topics:
        if topic_matches(str(pattern), topic):
            return True
    return False
