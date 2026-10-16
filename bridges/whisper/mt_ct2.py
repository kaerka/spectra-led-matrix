"""CTranslate2 neural machine translation for the Whisper bridge.

Used when ASR and translation are separate stages, which is required on the
Hexagon NPU because the quantised Whisper model returns nothing for the
``translate`` task. Splitting them is also better for translation quality: the
translator sees whole sentences instead of per-chunk fragments.

Two measured facts shape this module (Radxa Dragon Q6A, QCS6490):

* Thread placement dominates. CTranslate2 across all 8 cores is ~8.6x slower
  than 2 threads pinned to the four Cortex-A78s, because the A78s stall waiting
  on the A55s. Hence BIG_CORES / default intra_threads of 2.
* Fragmented input costs ~3.6 BLEU versus whole sentences, so text is buffered
  to sentence boundaries before translating (see SentenceBuffer).

Models are CTranslate2 conversions of Helsinki-NLP opus-mt pairs (~77MB each at
int8), laid out as ``<models_dir>/opus-<src>-<tgt>-int8``.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

DEFAULT_MODELS_DIR = "/data/spectra/models/mt"
BIG_CORES = frozenset({4, 5, 6, 7})      # Cortex-A78; 0-3 are Cortex-A55

_TRANSLATORS: Dict[Tuple[str, str], "Ct2Pair"] = {}
_BY_MODEL: Dict[Tuple[Path, str], "Ct2Pair"] = {}
_BUFFERS: Dict[Tuple[str, str], "SentenceBuffer"] = {}
_MISSING: Set[Tuple[str, str]] = set()

# Sentence end: terminator, optional closing quote/bracket, then whitespace or end.
_SENTENCE_END = re.compile(r'(?<=[.!?\u2026])["\u00bb\u201d\')\]]*(?:\s+|$)')


class Ct2Unavailable(RuntimeError):
    pass


def pin_to_big_cores() -> bool:
    """Restrict this process to the A78 cores. Returns True if applied."""
    try:
        available = set(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return False
    wanted = available & set(BIG_CORES)
    if not wanted or wanted == available:
        return False
    try:
        os.sched_setaffinity(0, wanted)
        return True
    except OSError:
        return False


def split_sentences(text: str) -> Tuple[List[str], str]:
    """Split into complete sentences plus any trailing incomplete remainder."""
    text = text.strip()
    if not text:
        return [], ""
    parts: List[str] = []
    pos = 0
    for m in _SENTENCE_END.finditer(text):
        chunk = text[pos:m.end()].strip()
        if chunk:
            parts.append(chunk)
        pos = m.end()
    return parts, text[pos:].strip()


class SentenceBuffer:
    """Hold partial sentences across chunks so the translator sees whole ones.

    A trailing fragment is kept until the next chunk completes it. It is released
    anyway once it is too old or too long, so a speaker who never produces a
    terminator still gets output.
    """

    def __init__(self, max_hold_seconds: float = 6.0, max_hold_chars: int = 400) -> None:
        self._pending = ""
        self._since = 0.0
        self._max_seconds = max_hold_seconds
        self._max_chars = max_hold_chars

    def add(self, text: str) -> str:
        text = (text or "").strip()
        if text:
            self._pending = f"{self._pending} {text}".strip() if self._pending else text
            if not self._since:
                self._since = time.monotonic()
        if not self._pending:
            return ""

        complete, remainder = split_sentences(self._pending)
        held_too_long = self._since and (time.monotonic() - self._since) >= self._max_seconds
        if remainder and (held_too_long or len(remainder) >= self._max_chars):
            complete.append(remainder)
            remainder = ""

        self._pending = remainder
        self._since = time.monotonic() if remainder else 0.0
        return " ".join(complete).strip()

    def stale(self) -> bool:
        """True if a fragment is held and its hold time has expired.

        Lets a caller release trailing speech when no further audio arrives,
        which ``add`` alone cannot do because it only runs on new input.
        """
        if not self._pending or not self._since:
            return False
        return (time.monotonic() - self._since) >= self._max_seconds

    def flush(self) -> str:
        out, self._pending, self._since = self._pending.strip(), "", 0.0
        return out


class _SpmTokenizer:
    """SentencePiece tokeniser for Marian/opus-mt CTranslate2 models.

    Preferred over transformers because it needs only sentencepiece, keeping
    torch and the transformers stack out of the deployed venv.
    """

    def __init__(self, model_dir: Path) -> None:
        import sentencepiece as spm

        self._src = spm.SentencePieceProcessor(model_file=str(model_dir / "source.spm"))
        self._tgt = spm.SentencePieceProcessor(model_file=str(model_dir / "target.spm"))

    def encode(self, text: str) -> List[str]:
        return self._src.encode(text, out_type=str) + ["</s>"]

    def decode(self, tokens: List[str]) -> str:
        return self._tgt.decode([t for t in tokens if t not in ("</s>", "<pad>", "<unk>")])


class _HfTokenizer:
    """transformers fallback, needed for NLLB's tokeniser."""

    def __init__(self, model_dir: Path, src: str, nllb: bool) -> None:
        from transformers import AutoTokenizer

        kwargs = {"src_lang": _nllb_code(src)} if nllb else {}
        self._tok = AutoTokenizer.from_pretrained(str(model_dir), **kwargs)

    def encode(self, text: str) -> List[str]:
        return self._tok.convert_ids_to_tokens(self._tok.encode(text))

    def decode(self, tokens: List[str]) -> str:
        return self._tok.decode(self._tok.convert_tokens_to_ids(tokens),
                                skip_special_tokens=True)


class Ct2Pair:
    def __init__(self, model_dir: Path, src: str, tgt: str, cfg: Dict[str, Any]) -> None:
        try:
            import ctranslate2
        except ImportError as exc:
            raise Ct2Unavailable(f"ctranslate2 not installed: {exc}") from exc

        mt = cfg.get("ct2", {}) if isinstance(cfg.get("ct2"), dict) else {}
        self.src, self.tgt = src, tgt
        self.beam = int(mt.get("beam_size", 2))        # beam 2 measured best on BLEU and time
        self.max_repeats = int(mt.get("max_repeats", 3))
        self.retry_penalty = float(mt.get("retry_repetition_penalty", 1.2))
        threads = int(mt.get("intra_threads", 2))
        self._nllb = "nllb" in model_dir.name.lower()

        has_spm = (model_dir / "source.spm").is_file() and (model_dir / "target.spm").is_file()
        if has_spm and not self._nllb:
            self._tok: Any = _SpmTokenizer(model_dir)
            self.tokenizer = "sentencepiece"
        else:
            self._tok = _HfTokenizer(model_dir, src, self._nllb)
            self.tokenizer = "transformers"

        self._model = ctranslate2.Translator(
            str(model_dir), device="cpu", compute_type=str(mt.get("compute_type", "int8")),
            inter_threads=1, intra_threads=threads,
        )

    def translate(self, text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        tokens = self._tok.encode(text)
        # Repetitive input (sung refrains, Whisper loops) can send opus-mt into
        # an endless "for, for, for, ..." that only stops at the length limit.
        kwargs: Dict[str, Any] = {
            "beam_size": self.beam,
            "max_decoding_length": 2 * len(tokens) + 16,
        }
        if self._nllb:
            kwargs["target_prefix"] = [[_nllb_code(self.tgt)]]
        out, runaway = collapse_repeats(self._decode(tokens, kwargs), self.max_repeats)
        if runaway and self.retry_penalty > 1.0:
            # A penalty on every call would reword legitimate refrains, so it
            # is applied only to output that has already degenerated.
            kwargs["repetition_penalty"] = self.retry_penalty
            out, _ = collapse_repeats(self._decode(tokens, kwargs), self.max_repeats)
        return out

    def _decode(self, tokens: List[str], kwargs: Dict[str, Any]) -> str:
        result = self._model.translate_batch([tokens], **kwargs)
        hyp = result[0].hypotheses[0]
        if self._nllb and hyp and hyp[0] == _nllb_code(self.tgt):
            hyp = hyp[1:]
        return self._tok.decode(hyp).strip()


_WORD_EDGE = ".,!?;:\u2026\"'\u00ab\u00bb\u201c\u201d()[]-\u2014"


def collapse_repeats(text: str, max_repeats: int = 3) -> Tuple[str, bool]:
    """Cap runs of a word or short phrase (up to 4 words) at max_repeats.

    Returns the text and whether anything was cut. Comparison ignores case and
    surrounding punctuation, so "for, for, For." counts as one repeated word.
    """
    words = text.split()
    norm = [w.strip(_WORD_EDGE).lower() for w in words]
    cut = False
    for n in range(1, 5):
        out_words: List[str] = []
        out_norm: List[str] = []
        i = 0
        while i < len(words):
            unit = norm[i:i + n]
            reps = 1
            if len(unit) == n and any(unit):
                while norm[i + reps * n:i + (reps + 1) * n] == unit:
                    reps += 1
            if reps > max_repeats:
                keep = max_repeats * n
                kept = words[i:i + keep]
                kept[-1] = kept[-1].rstrip(",;:") + ("" if kept[-1].endswith("...") else "...")
                out_words += kept
                out_norm += norm[i:i + keep]
                i += reps * n
                cut = True
            else:
                out_words.append(words[i])
                out_norm.append(norm[i])
                i += 1
        words, norm = out_words, out_norm
    return " ".join(words), cut


_NLLB_CODES = {
    "ru": "rus_Cyrl", "en": "eng_Latn", "uk": "ukr_Cyrl", "pl": "pol_Latn",
    "de": "deu_Latn", "fr": "fra_Latn", "es": "spa_Latn", "zh": "zho_Hans",
    "be": "bel_Cyrl", "kk": "kaz_Cyrl", "ar": "arb_Arab", "tr": "tur_Latn",
}


def _nllb_code(code: str) -> str:
    return _NLLB_CODES.get(code, f"{code}_Latn")


def _candidate_dirs(models_dir: Path, src: str, tgt: str) -> List[Path]:
    return [
        models_dir / f"opus-{src}-{tgt}-int8",
        models_dir / f"opus-mt-{src}-{tgt}-int8",
        models_dir / f"{src}-{tgt}",
        models_dir / "nllb600-int8",        # multilingual fallback, much slower
    ]


def get_translator(src: str, tgt: str, cfg: Dict[str, Any]) -> Ct2Pair:
    key = (src, tgt)
    cached = _TRANSLATORS.get(key)
    if cached is not None:
        return cached
    mt = cfg.get("ct2", {}) if isinstance(cfg.get("ct2"), dict) else {}
    models_dir = Path(str(mt.get("models_dir", DEFAULT_MODELS_DIR)))
    if key not in _MISSING:
        for candidate in _candidate_dirs(models_dir, src, tgt):
            if (candidate / "model.bin").is_file():
                # Several languages can link to one multi-source model (e.g.
                # pt and ro -> ROMANCE-en); load it once.
                real = (candidate.resolve(), tgt)
                pair = _BY_MODEL.get(real)
                if pair is None:
                    pair = Ct2Pair(candidate, src, tgt, cfg)
                    _BY_MODEL[real] = pair
                print(f"CT2 translator {src}->{tgt}: {candidate.resolve().name} "
                      f"(beam {pair.beam}, {pair.tokenizer})", flush=True)
                _TRANSLATORS[key] = pair
                return pair
        # Language auto-detect can name any of Whisper's 99 languages, including
        # misdetections on noise; don't rescan the disk for each such chunk.
        _MISSING.add(key)
    raise Ct2Unavailable(
        f"No CTranslate2 model for {src}->{tgt} under {models_dir}. "
        f"Convert one with: ct2-transformers-converter --model Helsinki-NLP/opus-mt-{src}-{tgt} "
        f"--output_dir {models_dir}/opus-{src}-{tgt}-int8 --quantization int8 "
        f"--copy_files source.spm target.spm"
    )


def translate_buffered(text: str, src: str, tgt: str, cfg: Dict[str, Any]) -> Tuple[str, str]:
    """Buffer to sentence boundaries, then translate.

    Returns ``(translated, source_consumed)``. Both are empty while a fragment is
    still being held for the next chunk. Raises Ct2Unavailable, before buffering
    anything, when there is no model for the pair.
    """
    if src == tgt:
        return text.strip(), text.strip()

    key = (src, tgt)
    if not text.strip() and key not in _BUFFERS:
        # Nothing to translate or release; don't report a missing model for
        # an empty chunk (Whisper still names a language for silence).
        return "", ""

    get_translator(src, tgt, cfg)
    mt = cfg.get("ct2", {}) if isinstance(cfg.get("ct2"), dict) else {}
    buf = _BUFFERS.get(key)
    if buf is None:
        buf = SentenceBuffer(
            max_hold_seconds=float(mt.get("max_hold_seconds", 6.0)),
            max_hold_chars=int(mt.get("max_hold_chars", 400)),
        )
        _BUFFERS[key] = buf

    if not bool(mt.get("buffer_sentences", True)):
        source = text.strip()
        return (get_translator(src, tgt, cfg).translate(source), source) if source else ("", "")

    source = buf.add(text)
    if not source:
        return "", ""
    return get_translator(src, tgt, cfg).translate(source), source


def flush_pending(tgt: str, cfg: Dict[str, Any], *, force: bool = False) -> List[Tuple[str, str, str]]:
    """Release held fragments as ``[(source_lang, translated, source_text), ...]``.

    Covers every source language with a buffer, since under language auto-detect
    there is one per detected language. Without ``force`` only fragments held
    longer than max_hold_seconds are released.
    """
    released: List[Tuple[str, str, str]] = []
    for (src, buf_tgt), buf in list(_BUFFERS.items()):
        if buf_tgt != tgt or not (force or buf.stale()):
            continue
        source = buf.flush()
        if source:
            released.append((src, get_translator(src, tgt, cfg).translate(source), source))
    return released
