"""Tests for custom messages: python -m unittest display.messages.test_messages"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from display.messages import store
from display.messages.schedule import current_showing, eligible, next_showing
from display.messages.schema import MessageError, for_target, normalize_message, normalize_messages

TZ = ZoneInfo("America/New_York")

GOALS = {
    "id": "goals",
    "name": "Goals",
    "lines": [
        {"text": "Goals:", "size": "large", "color": [255, 200, 0]},
        {"text": "- Workout 4 days a week", "size": "medium"},
        {"text": "- No alcohol from 10/02/26 to 03/02/27", "size": "small", "color": [120, 200, 255]},
    ],
    "every_minutes": 30,
    "duration_seconds": 15,
}


def msg(**overrides):
    return normalize_message({**GOALS, **overrides})


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=TZ)


class SchemaTests(unittest.TestCase):
    def test_defaults(self):
        m = msg()
        self.assertTrue(m["enabled"])
        self.assertEqual(m["days"], ["mon", "tue", "wed", "thu", "fri", "sat", "sun"])
        self.assertEqual(m["targets"], ["all"])
        self.assertEqual(m["lines"][1]["color"], [255, 255, 255])
        self.assertIsNone(m["active_from"])

    def test_rejects_bad_input(self):
        bad = [
            {"lines": []},
            {"lines": GOALS["lines"] + [{"text": "four"}]},
            {"lines": [{"text": "  "}]},
            {"lines": [{"text": "x", "color": [256, 0, 0]}]},
            {"lines": [{"text": "x", "size": "huge"}]},
            {"every_minutes": 0},
            {"duration_seconds": 1},
            {"active_from": "25:00", "active_until": "06:00"},
            {"active_from": "08:00"},
            {"start_date": "2027-03-02", "end_date": "2026-10-02"},
            {"days": ["someday"]},
            {"id": "has space"},
        ]
        for overrides in bad:
            with self.subTest(overrides=overrides), self.assertRaises(MessageError):
                normalize_message({**GOALS, **overrides})

    def test_duplicate_ids(self):
        with self.assertRaises(MessageError):
            normalize_messages([GOALS, GOALS])

    def test_for_target(self):
        a = msg(id="a")
        b = msg(id="b", targets=["upper"])
        c = msg(id="c", targets=["matrixportal-s3"])
        self.assertEqual([m["id"] for m in for_target([a, b, c], "upper")], ["a", "b"])
        self.assertEqual([m["id"] for m in for_target([a, b, c], "lower")], ["a"])


class ScheduleTests(unittest.TestCase):
    def test_window_aligned_to_slot(self):
        messages = [msg()]
        self.assertIsNotNone(current_showing(messages, at("2026-10-05T10:30:00")))
        self.assertIsNotNone(current_showing(messages, at("2026-10-05T10:30:14")))
        self.assertIsNone(current_showing(messages, at("2026-10-05T10:30:15")))
        self.assertIsNone(current_showing(messages, at("2026-10-05T10:45:00")))

    def test_shared_slot_runs_back_to_back(self):
        first = msg(id="first", every_minutes=30, duration_seconds=10)
        second = msg(id="second", every_minutes=60, duration_seconds=20)
        messages = [first, second]
        self.assertEqual(current_showing(messages, at("2026-10-05T11:00:05")).message["id"], "first")
        self.assertEqual(current_showing(messages, at("2026-10-05T11:00:12")).message["id"], "second")
        self.assertIsNone(current_showing(messages, at("2026-10-05T11:00:31")))
        # Only "first" is due at :30, so it isn't followed by anything.
        self.assertIsNone(current_showing(messages, at("2026-10-05T11:30:12")))

    def test_days_hours_and_dates(self):
        weekdays = msg(days=["mon", "tue", "wed", "thu", "fri"])
        self.assertTrue(eligible(weekdays, at("2026-10-05T10:00")))      # Monday
        self.assertFalse(eligible(weekdays, at("2026-10-04T10:00")))     # Sunday

        overnight = msg(active_from="22:00", active_until="06:00")
        self.assertTrue(eligible(overnight, at("2026-10-05T23:30")))
        self.assertTrue(eligible(overnight, at("2026-10-05T05:30")))
        self.assertFalse(eligible(overnight, at("2026-10-05T12:00")))

        dated = msg(start_date="2026-10-02", end_date="2027-03-02")
        self.assertFalse(eligible(dated, at("2026-10-01T12:00")))
        self.assertTrue(eligible(dated, at("2026-10-02T00:00")))
        self.assertTrue(eligible(dated, at("2027-03-02T23:59")))
        self.assertFalse(eligible(dated, at("2027-03-03T00:00")))

        self.assertFalse(eligible(msg(enabled=False), at("2026-10-05T10:00")))

    def test_next_showing(self):
        messages = [msg(every_minutes=60, active_from="09:00", active_until="17:00")]
        nxt = next_showing(messages, at("2026-10-05T17:30:00"))
        self.assertEqual(nxt.start, at("2026-10-06T09:00:00"))
        nxt = next_showing(messages, at("2026-10-05T10:00:05"))
        self.assertEqual(nxt.start, at("2026-10-05T11:00:00"))
        self.assertIsNone(next_showing([msg(enabled=False)], at("2026-10-05T10:00")))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("SPECTRA_DATA_ROOT")
        os.environ["SPECTRA_DATA_ROOT"] = self._tmp.name

    def tearDown(self):
        if self._old is None:
            os.environ.pop("SPECTRA_DATA_ROOT", None)
        else:
            os.environ["SPECTRA_DATA_ROOT"] = self._old
        self._tmp.cleanup()

    def test_roundtrip_and_revision(self):
        self.assertEqual(store.load_state()["messages"], [])
        saved = store.save_messages([GOALS])
        loaded = store.load_state()
        self.assertEqual(loaded["messages"][0]["id"], "goals")
        self.assertEqual(loaded["revision"], saved["revision"])
        self.assertEqual(saved["revision"], store.revision_of(normalize_messages([GOALS])))

    def test_corrupt_file_shows_nothing(self):
        path = Path(self._tmp.name) / "config" / store.STATE_NAME
        path.parent.mkdir(parents=True)
        path.write_text("{not json")
        self.assertEqual(store.load_state()["messages"], [])

    def test_preview_expires(self):
        payload = store.set_preview(GOALS, seconds=5)
        self.assertIsNotNone(store.load_preview(payload["started_at"] + 4))
        self.assertIsNone(store.load_preview(payload["started_at"] + 6))
        self.assertIsNone(store.load_preview(payload["started_at"] + 1))   # expired file was removed


try:
    from display.messages.render import FONT_PATH, _pad, build_content, fit_layout
    HAVE_RENDER = Path(FONT_PATH).is_file()
except ImportError:
    HAVE_RENDER = False


@unittest.skipUnless(HAVE_RENDER, "needs Pillow and DejaVu fonts")
class RenderTests(unittest.TestCase):
    def test_example_fits_without_scrolling(self):
        lines = msg()["lines"]
        for width, height in [(192, 192), (64, 64), (64, 48)]:
            with self.subTest(size=(width, height)):
                img = build_content(lines, width, height)
                self.assertLessEqual(img.height, height - 2 * _pad(width, height))

    def test_wall_uses_nominal_sizes(self):
        blocks, _gap, _h, scale = fit_layout(msg()["lines"], 192, 192)
        self.assertEqual(scale, 1.0)
        self.assertEqual([font.size for font, _rows, _c in blocks], [30, 22, 16])

    def test_too_much_text_scrolls_at_minimum_size(self):
        lines = [{"text": "word " * 15, "size": "large", "color": [255, 255, 255]}]
        img = build_content(lines, 32, 32)
        self.assertGreater(img.height, 28)


if __name__ == "__main__":
    unittest.main()
