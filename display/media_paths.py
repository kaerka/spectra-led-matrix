"""Resolve matrix animation directories when the display service runs as root."""

from __future__ import annotations

import os
import pwd
from typing import Iterable, List


def _unique_existing_dirs(paths: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for path in paths:
        norm = os.path.normpath(path)
        if norm in seen:
            continue
        seen.add(norm)
        if os.path.isdir(norm):
            out.append(norm)
    return out


def _home_candidates() -> List[str]:
    homes: List[str] = []
    env_home = os.environ.get("SPECTRA_MATRIX_HOME", "").strip()
    if env_home:
        homes.append(env_home)
    if os.geteuid() == 0:
        # Prefer SPECTRA_MATRIX_USER; fall back to the spectra service account.
        for user in (
            os.environ.get("SPECTRA_MATRIX_USER", "").strip(),
            "spectra",
        ):
            if not user:
                continue
            try:
                homes.append(pwd.getpwnam(user).pw_dir)
            except KeyError:
                continue
    homes.append(os.path.expanduser("~"))
    return homes


def gif_animations_dirs() -> List[str]:
    data_root = os.environ.get("SPECTRA_DATA_ROOT", "/data/spectra")
    candidates = [os.path.join(data_root, "media", "gifs")]
    for home in _home_candidates():
        candidates.append(os.path.join(home, "matrix-gif-animations"))
    return _unique_existing_dirs(candidates)


def mp4_animations_dirs() -> List[str]:
    data_root = os.environ.get("SPECTRA_DATA_ROOT", "/data/spectra")
    candidates = [os.path.join(data_root, "media", "mp4")]
    for home in _home_candidates():
        candidates.append(os.path.join(home, "matrix-mp4-animations"))
    return _unique_existing_dirs(candidates)


def primary_gif_animations_dir() -> str:
    dirs = gif_animations_dirs()
    if dirs:
        return dirs[0]
    home = _home_candidates()[0]
    return os.path.join(home, "matrix-gif-animations")


def primary_mp4_animations_dir() -> str:
    dirs = mp4_animations_dirs()
    if dirs:
        return dirs[0]
    home = _home_candidates()[0]
    return os.path.join(home, "matrix-mp4-animations")
