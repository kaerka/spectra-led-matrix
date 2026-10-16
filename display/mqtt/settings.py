"""Runtime MQTT overlay toggles — shared between web API and display worker."""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from display.mqtt.sources import SOURCE_CATALOG, wall_source_ids

_lock = threading.RLock()
_cache: dict = {"mtime": 0.0, "settings": None}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _settings_paths() -> list[Path]:
    data_root = os.environ.get("SPECTRA_DATA_ROOT", "/data/spectra")
    root = _repo_root()
    return [
        Path(data_root) / "config" / "mqtt_overlay_state.json",
        root / "config" / "mqtt_overlay_state.json",
        root / "config" / "mqtt_overlay_state.example.json",
    ]


def _writable_path() -> Path:
    data_root = Path(os.environ.get("SPECTRA_DATA_ROOT", "/data/spectra"))
    preferred = data_root / "config" / "mqtt_overlay_state.json"
    if preferred.parent.exists() or data_root.exists():
        return preferred
    return _repo_root() / "config" / "mqtt_overlay_state.json"


@dataclass
class MqttOverlaySettings:
    overlay_enabled: bool = True
    sources: Dict[str, bool] = field(default_factory=dict)
    updated_at: Optional[float] = None

    def source_enabled(self, source_id: str) -> bool:
        return self.sources.get(source_id, True)

    def with_wall_sources(self, wall_sources: List[str]) -> "MqttOverlaySettings":
        """Return settings restricted to sources available on this wall."""
        pruned = {sid: self.source_enabled(sid) for sid in wall_sources}
        return MqttOverlaySettings(
            overlay_enabled=self.overlay_enabled,
            sources=pruned,
            updated_at=self.updated_at,
        )


def default_settings(subscribed_topics: Optional[List[str]] = None) -> MqttOverlaySettings:
    topics = subscribed_topics or []
    ids = wall_source_ids(topics) if topics else list(SOURCE_CATALOG)
    return MqttOverlaySettings(
        overlay_enabled=True,
        sources={sid: True for sid in ids},
    )


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fp:
        return json.load(fp)


def load_overlay_settings(
    subscribed_topics: Optional[List[str]] = None,
    path: Optional[Path] = None,
) -> MqttOverlaySettings:
    """Load runtime overlay toggles; merge defaults for any new wall sources."""
    write_path = path or _writable_path()
    with _lock:
        try:
            mtime = write_path.stat().st_mtime if write_path.is_file() else 0.0
        except OSError:
            mtime = 0.0

        if _cache["settings"] is not None and mtime == _cache["mtime"]:
            settings = _cache["settings"]
            if subscribed_topics is not None:
                return settings.with_wall_sources(wall_source_ids(subscribed_topics))
            return settings

        raw: dict = {}
        for candidate in _settings_paths():
            if candidate.is_file():
                try:
                    raw = _read_json(candidate)
                    if candidate == write_path:
                        mtime = candidate.stat().st_mtime
                    break
                except (OSError, ValueError):
                    continue

        wall_ids = wall_source_ids(subscribed_topics or [])
        if not raw:
            settings = default_settings(subscribed_topics)
        else:
            src_raw = raw.get("sources") or {}
            sources = {sid: bool(src_raw.get(sid, True)) for sid in wall_ids}
            settings = MqttOverlaySettings(
                overlay_enabled=bool(raw.get("overlay_enabled", True)),
                sources=sources,
                updated_at=raw.get("updated_at"),
            )

        _cache["mtime"] = mtime
        _cache["settings"] = settings
        return settings


def save_overlay_settings(
    settings: MqttOverlaySettings,
    *,
    subscribed_topics: Optional[List[str]] = None,
    path: Optional[Path] = None,
) -> MqttOverlaySettings:
    write_path = path or _writable_path()
    write_path.parent.mkdir(parents=True, exist_ok=True)

    wall_ids = wall_source_ids(subscribed_topics or [])
    pruned = settings.with_wall_sources(wall_ids)
    pruned.updated_at = time.time()

    with _lock:
        with write_path.open("w", encoding="utf-8") as fp:
            json.dump(asdict(pruned), fp, indent=2)
            fp.write("\n")
        try:
            _cache["mtime"] = write_path.stat().st_mtime
        except OSError:
            _cache["mtime"] = pruned.updated_at or time.time()
        _cache["settings"] = pruned
    return pruned


def update_overlay_settings(
    *,
    overlay_enabled: Optional[bool] = None,
    sources: Optional[Dict[str, bool]] = None,
    subscribed_topics: Optional[List[str]] = None,
) -> MqttOverlaySettings:
    current = load_overlay_settings(subscribed_topics)
    if overlay_enabled is not None:
        current.overlay_enabled = overlay_enabled
    if sources:
        for source_id, enabled in sources.items():
            if source_id in current.sources:
                current.sources[source_id] = bool(enabled)
    return save_overlay_settings(current, subscribed_topics=subscribed_topics)
