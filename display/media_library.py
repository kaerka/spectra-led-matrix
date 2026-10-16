"""Scan local GIF/MP4 animation libraries."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import List

from display.media_paths import (
    gif_animations_dirs,
    mp4_animations_dirs,
    primary_gif_animations_dir,
    primary_mp4_animations_dir,
)

MEDIA_EXTENSIONS = (".gif", ".mp4", ".mov", ".avi", ".mkv", ".webm")

GIF_DIR = primary_gif_animations_dir()
MP4_DIR = primary_mp4_animations_dir()

_CACHE_TTL_SECONDS = 60
_cache: dict = {"at": 0.0, "files": []}


@dataclass(frozen=True)
class MediaFile:
    path: str
    name: str
    kind: str  # "gif" or "video"
    folder: str


def _scan_dir(directory: str, kind: str) -> List[MediaFile]:
    if not os.path.isdir(directory):
        return []
    files: List[MediaFile] = []
    for name in sorted(os.listdir(directory), key=str.lower):
        if not name.lower().endswith(MEDIA_EXTENSIONS):
            continue
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            files.append(MediaFile(path=path, name=name, kind=kind, folder=os.path.basename(directory)))
    return files


def list_media_files(*, refresh: bool = False) -> List[MediaFile]:
    now = time.time()
    if not refresh and _cache["files"] and now - _cache["at"] < _CACHE_TTL_SECONDS:
        return _cache["files"]
    files: List[MediaFile] = []
    for directory in gif_animations_dirs():
        files.extend(_scan_dir(directory, "gif"))
    for directory in mp4_animations_dirs():
        files.extend(_scan_dir(directory, "video"))
    _cache["files"] = files
    _cache["at"] = now
    return files


def default_media_path() -> str | None:
    files = list_media_files()
    return files[0].path if files else None


def resolve_media_path(path: str | None) -> str | None:
    if not path:
        return default_media_path()
    if not os.path.isfile(path):
        return default_media_path()
    return path
