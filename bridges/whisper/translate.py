"""Translation helpers for the Whisper MQTT pipeline.

| Path | When |
| --- | --- |
| ``whisper`` + ``target_language: en`` | faster-whisper ``task=translate`` (any language → English) |
| ``ct2`` | transcribe → CTranslate2 opus-mt, buffered to whole sentences |
| ``argos`` (or whisper + non-en target) | transcribe → Argos Translate (e.g. English → Russian) |
| ``off`` | transcribe only |

``ct2`` is required with ``engine: npu``: the quantised Hexagon Whisper model
returns nothing for the ``translate`` task, so translation must be a second stage.

Stubbed post-ASR: ``coral``, ``remote``, ``mercury``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

WHISPER_TRANSLATE_ENGINE = "whisper"
ARGOS_ENGINE = "argos"
CT2_ENGINE = "ct2"
POST_ASR_ENGINES = frozenset({ARGOS_ENGINE, CT2_ENGINE, "coral", "remote", "mercury"})
_ARGOS_READY: Set[Tuple[str, str]] = set()
_CT2_WARNED: Set[Tuple[str, str]] = set()


def normalize_lang(code: Any, default: str = "en") -> str:
    if code is None:
        return default
    text = str(code).strip().lower()
    if text in ("", "auto", "null", "none"):
        return default
    return text.split("-")[0]


def resolve_translate_engine(cfg: Dict[str, Any]) -> str:
    raw = str(
        cfg.get("translate_engine", cfg.get("translation_engine", "off"))
    ).lower().strip()
    if raw in ("", "none", "false", "0", "off"):
        return "off"
    if raw in {WHISPER_TRANSLATE_ENGINE, *POST_ASR_ENGINES}:
        return raw
    raise ValueError(f"Unknown translate_engine: {raw!r}")


def effective_translate_engine(cfg: Dict[str, Any]) -> str:
    """Resolve engine after applying target-language rules."""
    engine = resolve_translate_engine(cfg)
    if engine == "off":
        return "off"
    target = normalize_lang(cfg.get("target_language", "en"), default="en")
    if engine == WHISPER_TRANSLATE_ENGINE and target != "en":
        return str(cfg.get("whisper_fallback_engine", ARGOS_ENGINE)).lower()
    return engine


def resolve_language(cfg: Dict[str, Any]) -> Optional[str]:
    lang = cfg.get("language")
    if lang is None:
        return None
    text = str(lang).strip().lower()
    if text in ("", "auto", "null", "none"):
        return None
    return str(lang).strip()


def resolve_source_language(cfg: Dict[str, Any], detected: Optional[str]) -> str:
    explicit = cfg.get("source_language")
    if explicit is not None and str(explicit).strip().lower() not in ("", "auto"):
        return normalize_lang(explicit)
    if detected:
        return normalize_lang(detected)
    configured = resolve_language(cfg)
    if configured:
        return normalize_lang(configured)
    return "en"


def transcribe_options(cfg: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """Build faster-whisper kwargs and return (options, effective_engine)."""
    engine = effective_translate_engine(cfg)
    language = resolve_language(cfg)

    task = "translate" if engine == WHISPER_TRANSLATE_ENGINE else "transcribe"

    options: Dict[str, Any] = {
        "language": language,
        "task": task,
        "vad_filter": bool(cfg.get("vad_filter", True)),
        "no_speech_threshold": float(cfg.get("no_speech_threshold", 0.65)),
        "log_prob_threshold": float(cfg.get("log_prob_threshold", -1.0)),
        "compression_ratio_threshold": float(cfg.get("compression_ratio_threshold", 2.4)),
        "condition_on_previous_text": False,
    }
    return options, engine


def ensure_argos_language_pair(from_code: str, to_code: str) -> None:
    from_code = normalize_lang(from_code)
    to_code = normalize_lang(to_code)
    key = (from_code, to_code)
    if key in _ARGOS_READY:
        return

    import argostranslate.package
    import argostranslate.translate

    installed = argostranslate.translate.get_installed_languages()
    from_lang = next((lang for lang in installed if lang.code == from_code), None)
    to_lang = next((lang for lang in installed if lang.code == to_code), None)
    if from_lang and to_lang and from_lang.get_translation(to_lang):
        _ARGOS_READY.add(key)
        return

    argostranslate.package.update_package_index()
    available = argostranslate.package.get_available_packages()
    package = next(
        (pkg for pkg in available if pkg.from_code == from_code and pkg.to_code == to_code),
        None,
    )
    if package is None:
        raise RuntimeError(f"No Argos Translate package for {from_code}→{to_code}")

    download_path = package.download()
    argostranslate.package.install_from_path(download_path)
    _ARGOS_READY.add(key)


def argos_translate(text: str, from_code: str, to_code: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return cleaned
    from_code = normalize_lang(from_code)
    to_code = normalize_lang(to_code)
    if from_code == to_code:
        return cleaned

    ensure_argos_language_pair(from_code, to_code)
    import argostranslate.translate

    translated = argostranslate.translate.translate(cleaned, from_code, to_code)
    return translated.strip()


def apply_post_translation_ex(
    text: str,
    cfg: Dict[str, Any],
    *,
    source_language: str,
    model: Any = None,
) -> Tuple[str, str]:
    """Translate after ASR.

    Returns ``(translated, source_consumed)``. For ``ct2`` these can differ from
    ``text``: it buffers to sentence boundaries, so a chunk ending mid-sentence
    yields ``("", "")`` and the held words are emitted with a later chunk.
    """
    engine = effective_translate_engine(cfg)
    if engine in ("off", WHISPER_TRANSLATE_ENGINE):
        return text, text

    target = normalize_lang(cfg.get("target_language", "en"), default="en")
    source = normalize_lang(source_language)

    if engine == ARGOS_ENGINE:
        return argos_translate(text, source, target), text

    if engine == CT2_ENGINE:
        from mt_ct2 import Ct2Unavailable, translate_buffered

        try:
            return translate_buffered(text, source, target, cfg)
        except Ct2Unavailable as exc:
            # Raising here would leave the chunk without a .done file, so the
            # service would crash-loop on it; publish the source text instead.
            if (source, target) not in _CT2_WARNED:
                _CT2_WARNED.add((source, target))
                print(f"Warning: {exc}; publishing {source} untranslated", flush=True)
            return text, text

    if engine in POST_ASR_ENGINES - {ARGOS_ENGINE, CT2_ENGINE}:
        raise NotImplementedError(
            f"translate_engine {engine!r} is not implemented yet; use ct2, argos or whisper."
        )
    raise ValueError(f"Unknown translate_engine: {engine!r}")


def apply_post_translation(
    text: str,
    cfg: Dict[str, Any],
    *,
    source_language: str,
    model: Any = None,
) -> str:
    translated, _ = apply_post_translation_ex(
        text, cfg, source_language=source_language, model=model
    )
    return translated


def build_transcript_meta(
    *,
    translate_engine: str,
    task: str,
    language: Optional[str],
    language_probability: Optional[float],
    target_language: str,
    source_language: Optional[str] = None,
    original_text: Optional[str] = None,
) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "task": task,
        "translate_engine": translate_engine,
        "target_language": normalize_lang(target_language),
    }
    if source_language:
        meta["source_language"] = normalize_lang(source_language)
    if language:
        meta["language"] = language
    if language_probability is not None:
        meta["language_probability"] = round(float(language_probability), 4)
    if original_text and original_text != "":
        meta["original_text"] = original_text
    return meta


def build_mqtt_payload(
    display_text: str,
    meta: Dict[str, Any],
    *,
    ttl: int,
    color: list,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "text": display_text,
        "ttl": ttl,
        "color": color,
    }
    if meta.get("translate_engine") not in ("off", None):
        payload["translate_engine"] = meta["translate_engine"]
    if meta.get("task"):
        payload["task"] = meta["task"]
    if meta.get("language"):
        payload["language"] = meta["language"]
    if meta.get("source_language"):
        payload["source_language"] = meta["source_language"]
    if meta.get("target_language"):
        payload["target_language"] = meta["target_language"]
    original = meta.get("original_text")
    if original and original.strip() and original.strip() != display_text.strip():
        payload["original_text"] = original.strip()
    return payload


def flush_pending_translation(
    cfg: Dict[str, Any],
    *,
    force: bool = False,
) -> List[Tuple[str, str, str]]:
    """Release text an engine is holding back, as ``[(source_lang, translated, source)]``.

    Only ``ct2`` buffers, so every other engine returns nothing. With ``force``
    fragments are released regardless of how long they have been held, for
    shutdown.
    """
    if effective_translate_engine(cfg) != CT2_ENGINE:
        return []

    from mt_ct2 import flush_pending

    target = normalize_lang(cfg.get("target_language", "en"), default="en")
    return flush_pending(target, cfg, force=force)
