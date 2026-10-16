"""Decide which custom message, if any, should be on screen right now.

Stateless: the answer depends only on the message list and the wall clock, so
every display computes the same windows (both walls show a message together)
and a restart neither skips nor repeats one.

Showings are aligned to local midnight: "every 30 minutes" means 00:00, 00:30,
01:00, ... When several messages share a slot they run back to back in list
order instead of the later ones never appearing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta
from typing import Any, Dict, List, Optional

from display.messages.schema import DAYS


@dataclass(frozen=True)
class Showing:
    message: Dict[str, Any]
    start: datetime
    end: datetime

    @property
    def key(self) -> str:
        return f"{self.message['id']}@{self.start.isoformat()}"


def _parse_hhmm(value: str) -> dtime:
    hours, minutes = value.split(":")
    return dtime(int(hours), int(minutes))


def eligible(message: Dict[str, Any], at: datetime) -> bool:
    """Whether the message may show at this local time (days, hours, dates)."""
    if not message.get("enabled", True):
        return False
    if DAYS[at.weekday()] not in message.get("days", DAYS):
        return False
    today = at.date().isoformat()
    if message.get("start_date") and today < message["start_date"]:
        return False
    if message.get("end_date") and today > message["end_date"]:
        return False
    if message.get("active_from") and message.get("active_until"):
        start = _parse_hhmm(message["active_from"])
        end = _parse_hhmm(message["active_until"])
        now_t = at.time().replace(second=0, microsecond=0)
        if start <= end:
            if not start <= now_t < end:
                return False
        elif end <= now_t < start:      # window wraps past midnight, e.g. 22:00-06:00
            return False
    return True


def _midnight(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _slot_minute(minutes_since_midnight: float, every: int) -> int:
    return int(minutes_since_midnight // every) * every


def _window(messages: List[Dict[str, Any]], i: int, midnight: datetime,
            slot_min: int) -> Optional[Showing]:
    msg = messages[i]
    slot = midnight + timedelta(minutes=slot_min)
    if not eligible(msg, slot):
        return None
    # Run after earlier messages that share this slot.
    offset = 0
    for earlier in messages[:i]:
        if slot_min % int(earlier["every_minutes"]) == 0 and eligible(earlier, slot):
            offset += int(earlier["duration_seconds"])
    start = slot + timedelta(seconds=offset)
    return Showing(msg, start, start + timedelta(seconds=int(msg["duration_seconds"])))


def current_showing(messages: List[Dict[str, Any]], now: datetime) -> Optional[Showing]:
    """The message whose window contains ``now``, or None."""
    midnight = _midnight(now)
    elapsed_min = (now - midnight).total_seconds() / 60.0
    for i, msg in enumerate(messages):
        showing = _window(messages, i, midnight, _slot_minute(elapsed_min, int(msg["every_minutes"])))
        if showing and showing.start <= now < showing.end:
            return showing
    return None


def next_showing(messages: List[Dict[str, Any]], now: datetime,
                 horizon_days: int = 2) -> Optional[Showing]:
    """The next window to start after ``now`` (for status in the UI)."""
    best: Optional[Showing] = None
    first_midnight = _midnight(now)
    for i, msg in enumerate(messages):
        every = int(msg["every_minutes"])
        for day in range(horizon_days + 1):
            midnight = _midnight(first_midnight + timedelta(days=day, hours=12))
            found = None
            for slot_min in range(0, 1440, every):
                if midnight + timedelta(minutes=slot_min) + timedelta(minutes=10) < now:
                    continue
                showing = _window(messages, i, midnight, slot_min)
                if showing and showing.start > now:
                    found = showing
                    break
            if found:
                if best is None or found.start < best.start:
                    best = found
                break
    return best
