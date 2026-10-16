"""python display/mqtt/test_purge.py"""

from __future__ import annotations

import importlib.util
import os
import tempfile
import time
import unittest
from pathlib import Path

# Load by path: importing the display.mqtt package pulls in rgbmatrix.
_spec = importlib.util.spec_from_file_location("purge", Path(__file__).with_name("purge.py"))
purge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(purge)


class PurgeMarkerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "config" / purge.MARKER_NAME

    def tearDown(self):
        self._tmp.cleanup()

    def test_never_purged(self):
        self.assertEqual(purge.purged_at(self.path), 0.0)

    def test_purge_covers_earlier_messages_only(self):
        before = time.time()
        stamp = purge.request_purge(self.path)
        self.assertGreaterEqual(stamp, before)
        self.assertEqual(purge.purged_at(self.path), stamp)
        self.assertLessEqual(before, purge.purged_at(self.path))      # earlier caption dropped
        self.assertGreater(time.time() + 1, purge.purged_at(self.path))  # later caption kept

    def test_second_purge_is_picked_up(self):
        first = purge.request_purge(self.path)
        time.sleep(0.02)
        os.utime(self.path, (first + 5, first + 5))   # force a new mtime on coarse filesystems
        second = purge.request_purge(self.path)
        self.assertEqual(purge.purged_at(self.path), second)


if __name__ == "__main__":
    unittest.main()
