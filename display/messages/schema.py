"""Custom message schema shared by the walls, the orchestrator and small boards.

Pure Python with no rgbmatrix or web imports, so the Pi5 orchestrator and the
tests can use it too. The same JSON is what small boards will receive.

A message::

    {
      "id": "goals",
      "name": "Goals",
      "enabled": true,
      "lines": [                                   # 1-3 lines
        {"text": "Goals:", "size": "large", "color": [255, 200, 0]},
        {"text": "Workout 4 days a week", "size": "medium", "color": [255, 255, 255]}
      ],
      "every_minutes": 30,                         # aligned to local midnight
      "duration_seconds": 15,
      "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
      "active_from": "08:00", "active_until": "22:00",   # optional; may wrap past midnight
      "start_date": "2026-10-02", "end_date": "2027-03-02",  # optional, inclusive
      "targets": ["all"]                           # or display ids
    }

Sizes are symbolic (small / medium / large) so each display maps them to its
own fonts; text is shrunk to fit, so one message works from 32x32 to 192x192.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List

SIZES = ("small", "medium", "large")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MAX_LINES = 3
MAX_LINE_CHARS = 80
MAX_MESSAGES = 20
MIN_EVERY_MINUTES = 1
MAX_EVERY_MINUTES = 1440
MIN_DURATION_SECONDS = 3
MAX_DURATION_SECONDS = 300
DEFAULT_COLOR = [255, 255, 255]

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class MessageError(ValueError):
    pass


def _color(value: Any, where: str) -> List[int]:
    if value is None:
        return list(DEFAULT_COLOR)
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise MessageError(f"{where}: color must be [r, g, b]")
    out = []
    for channel in value:
        if isinstance(channel, bool) or not isinstance(channel, int) or not 0 <= channel <= 255:
            raise MessageError(f"{where}: color values must be integers 0-255")
        out.append(channel)
    return out


def _int(value: Any, lo: int, hi: int, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise MessageError(f"{where} must be an integer {lo}-{hi}")
    return value


def _hhmm(value: Any, where: str):
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not _TIME_RE.match(value):
        raise MessageError(f"{where} must be HH:MM (24-hour)")
    return value


def _iso_date(value: Any, where: str):
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise MessageError(f"{where} must be YYYY-MM-DD") from exc


def normalize_line(raw: Any, where: str) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise MessageError(f"{where} must be an object")
    text = str(raw.get("text", "")).replace("\n", " ").strip()
    if len(text) > MAX_LINE_CHARS:
        raise MessageError(f"{where}: text is longer than {MAX_LINE_CHARS} characters")
    size = raw.get("size", "medium")
    if size not in SIZES:
        raise MessageError(f"{where}: size must be one of {', '.join(SIZES)}")
    return {"text": text, "size": size, "color": _color(raw.get("color"), where)}


def normalize_message(raw: Any, index: int = 0) -> Dict[str, Any]:
    where = f"message {index + 1}"
    if not isinstance(raw, dict):
        raise MessageError(f"{where} must be an object")

    msg_id = str(raw.get("id") or "").strip()
    if not _ID_RE.match(msg_id):
        raise MessageError(f"{where}: id must be 1-40 letters, digits, '-' or '_'")

    lines_raw = raw.get("lines")
    if not isinstance(lines_raw, list) or not 1 <= len(lines_raw) <= MAX_LINES:
        raise MessageError(f"{where}: needs 1-{MAX_LINES} lines")
    lines = [normalize_line(line, f"{where} line {i + 1}") for i, line in enumerate(lines_raw)]
    if not any(line["text"] for line in lines):
        raise MessageError(f"{where}: all lines are empty")

    days = raw.get("days") or list(DAYS)
    if not isinstance(days, list) or not days or any(d not in DAYS for d in days):
        raise MessageError(f"{where}: days must be a non-empty list of {', '.join(DAYS)}")

    active_from = _hhmm(raw.get("active_from"), f"{where} active_from")
    active_until = _hhmm(raw.get("active_until"), f"{where} active_until")
    if (active_from is None) != (active_until is None):
        raise MessageError(f"{where}: set both active_from and active_until, or neither")

    start_date = _iso_date(raw.get("start_date"), f"{where} start_date")
    end_date = _iso_date(raw.get("end_date"), f"{where} end_date")
    if start_date and end_date and end_date < start_date:
        raise MessageError(f"{where}: end_date is before start_date")

    targets = raw.get("targets") or ["all"]
    if not isinstance(targets, list) or not all(isinstance(t, str) and t for t in targets):
        raise MessageError(f"{where}: targets must be a list of display ids or ['all']")

    return {
        "id": msg_id,
        "name": str(raw.get("name") or msg_id).strip()[:60],
        "enabled": bool(raw.get("enabled", True)),
        "lines": lines,
        "every_minutes": _int(raw.get("every_minutes", 30), MIN_EVERY_MINUTES,
                              MAX_EVERY_MINUTES, f"{where} every_minutes"),
        "duration_seconds": _int(raw.get("duration_seconds", 15), MIN_DURATION_SECONDS,
                                 MAX_DURATION_SECONDS, f"{where} duration_seconds"),
        "days": [d for d in DAYS if d in days],
        "active_from": active_from,
        "active_until": active_until,
        "start_date": start_date,
        "end_date": end_date,
        "targets": sorted(set(targets)),
    }


def normalize_messages(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        raise MessageError("messages must be a list")
    if len(raw) > MAX_MESSAGES:
        raise MessageError(f"at most {MAX_MESSAGES} messages")
    messages = [normalize_message(item, i) for i, item in enumerate(raw)]
    seen = set()
    for msg in messages:
        if msg["id"] in seen:
            raise MessageError(f"duplicate message id {msg['id']!r}")
        seen.add(msg["id"])
    return messages


def for_target(messages: List[Dict[str, Any]], target_id: str) -> List[Dict[str, Any]]:
    """Messages addressed to one display ('all' matches every display)."""
    return [m for m in messages if "all" in m["targets"] or target_id in m["targets"]]
