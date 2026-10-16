"""Format Iris/Aether/Nightglass ecosystem JSON for matrix display."""

from __future__ import annotations

import json
from typing import Optional


def is_displayable_caption(text: str, *, min_ratio: float = 0.85) -> bool:
    """Reject decoded binary / protobuf mush (e.g. Meshtastic non-text packets)."""
    stripped = text.strip()
    if not stripped:
        return False
    if "\ufffd" in stripped:
        return False
    ok = 0
    for ch in stripped:
        if ch in "\n\t":
            ok += 1
        elif ch.isprintable():
            ok += 1
    return (ok / len(stripped)) >= min_ratio


def extract_display_text(raw: str, topic: str) -> Optional[str]:
    """Convert standard_header telemetry or simple JSON to a one-line caption."""
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        return None

    if not isinstance(obj, dict):
        if isinstance(obj, str):
            return obj.strip() or None
        return None

    if "text" in obj or "message" in obj:
        text = str(obj.get("text", obj.get("message", ""))).strip()
        return text if text and is_displayable_caption(text) else None

    header = obj.get("standard_header") or {}
    data = obj.get("data") or {}
    project = str(header.get("project", topic.split("/")[0] if topic else "node")).upper()
    node_id = str(header.get("node_id", ""))
    prefix = f"{project} {node_id}".strip()

    event_type = data.get("event_type")
    if event_type:
        parts = [prefix, str(event_type).replace("_", " ")]
        objects = data.get("objects")
        if isinstance(objects, list) and objects:
            top = objects[0]
            cls = top.get("class")
            conf = top.get("confidence")
            if cls:
                parts.append(str(cls))
            if conf is not None:
                parts.append(f"({int(float(conf) * 100)}%)")
        return ": ".join(parts)

    if isinstance(data.get("text"), str):
        caption = f"{prefix}: {data['text']}".strip()
        return caption if is_displayable_caption(caption) else None

    return prefix if is_displayable_caption(prefix) else None
