"""Heuristics to drop low-confidence Whisper output before MQTT publish."""

from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

DEFAULT_REJECT_PHRASES = (
    "thank you",
    "thanks for watching",
    "please subscribe",
    "subscribe",
    "subtitles by",
    "subtitle by",
    "amara.org",
    "www.",
    "http",
    "music",
    "applause",
    "silence",
)

_NON_WORD = re.compile(r"[^\w\s']+", re.UNICODE)


def _normalize(text: str) -> str:
    return _NON_WORD.sub("", text.lower()).strip()


def should_publish(
    text: str,
    segments: Sequence[Any],
    cfg: dict[str, Any],
) -> tuple[bool, str]:
    """Return (publish?, reason)."""
    cleaned = text.strip()
    if not cleaned:
        return False, "empty"

    min_chars = int(cfg.get("min_chars", 4))
    if len(_normalize(cleaned)) < min_chars:
        return False, "too short"

    min_words = int(cfg.get("min_words", 2))
    words = cleaned.split()
    if len(words) < min_words:
        return False, f"too few words ({len(words)} < {min_words})"

    if segments and not cfg.get("skip_logprob_filter", False):
        no_speech = [float(getattr(seg, "no_speech_prob", 0.0)) for seg in segments]
        avg_nsp = sum(no_speech) / len(no_speech)
        max_nsp = float(cfg.get("max_no_speech_prob", 0.55))
        if avg_nsp > max_nsp:
            return False, f"high no_speech_prob ({avg_nsp:.2f})"

        logprobs = [float(getattr(seg, "avg_logprob", -99.0)) for seg in segments]
        avg_lp = sum(logprobs) / len(logprobs)
        min_lp = float(cfg.get("min_avg_logprob", -0.75))
        if avg_lp < min_lp:
            return False, f"low logprob ({avg_lp:.2f})"
    elif segments:
        no_speech = [float(getattr(seg, "no_speech_prob", 0.0)) for seg in segments]
        avg_nsp = sum(no_speech) / len(no_speech)
        max_nsp = float(cfg.get("max_no_speech_prob", 0.55))
        if avg_nsp > max_nsp:
            return False, f"high no_speech_prob ({avg_nsp:.2f})"

    normalized = _normalize(cleaned)
    reject_phrases: Iterable[str] = cfg.get("reject_phrases", DEFAULT_REJECT_PHRASES)
    for phrase in reject_phrases:
        p = _normalize(str(phrase))
        if not p:
            continue
        if normalized == p or normalized.startswith(p + " "):
            return False, f"reject phrase ({phrase!r})"

    return True, "ok"


def publish_filter_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return cfg with relaxed thresholds when translation is enabled."""
    from translate import effective_translate_engine

    out = dict(cfg)
    if effective_translate_engine(cfg) == "off":
        return out
    out["skip_logprob_filter"] = bool(cfg.get("translate_skip_logprob", True))
    if not out["skip_logprob_filter"]:
        out["min_avg_logprob"] = float(cfg.get("min_avg_logprob_translate", -2.0))
    out["max_no_speech_prob"] = float(cfg.get("max_no_speech_prob_translate", 0.72))
    return out
