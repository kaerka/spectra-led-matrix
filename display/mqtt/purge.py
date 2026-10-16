"""Purge marker shared by the web API and the display worker (separate processes).

The web API records "drop everything that arrived before now"; the display
worker compares the current caption's arrival time against it on each pass.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

MARKER_NAME = "mqtt_purge.json"
_cache = {"mtime": None, "purged_at": 0.0}


def _marker_path() -> Path:
    data_root = Path(os.environ.get("SPECTRA_DATA_ROOT", "/data/spectra"))
    if (data_root / "config").exists() or data_root.exists():
        return data_root / "config" / MARKER_NAME
    return Path(__file__).resolve().parents[2] / "config" / MARKER_NAME


def request_purge(path: Optional[Path] = None) -> float:
    path = path or _marker_path()
    now = time.time()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"purged_at": now}) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return now


def purged_at(path: Optional[Path] = None) -> float:
    """Epoch of the last purge (0 if never); cached on mtime for the display loop."""
    path = path or _marker_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return 0.0
    if mtime != _cache["mtime"]:
        try:
            _cache["purged_at"] = float(json.loads(path.read_text(encoding="utf-8"))["purged_at"])
        except (OSError, ValueError, KeyError, TypeError):
            _cache["purged_at"] = mtime
        _cache["mtime"] = mtime
    return _cache["purged_at"]
