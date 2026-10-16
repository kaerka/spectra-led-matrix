"""Unit tests for whisper translation config helpers."""

from __future__ import annotations

import time
import unittest
from pathlib import Path
from unittest import mock

import mt_ct2
from filter import publish_filter_cfg
from mt_ct2 import SentenceBuffer, collapse_repeats, split_sentences

try:
    import paho.mqtt.client  # noqa: F401
except ImportError:  # transcribe() doesn't touch MQTT; keep the tests runnable without it
    import sys
    for name in ("paho", "paho.mqtt", "paho.mqtt.client"):
        sys.modules.setdefault(name, mock.MagicMock())
from transcribe_watch import transcribe
from translate import (
    apply_post_translation_ex,
    build_mqtt_payload,
    effective_translate_engine,
    flush_pending_translation,
    resolve_translate_engine,
    transcribe_options,
)


class TranslateConfigTests(unittest.TestCase):
    def test_whisper_to_english_uses_translate_task(self) -> None:
        options, engine = transcribe_options(
            {"translate_engine": "whisper", "target_language": "en", "language": "auto"}
        )
        self.assertEqual(engine, "whisper")
        self.assertEqual(options["task"], "translate")

    def test_whisper_with_russian_target_falls_back_to_argos(self) -> None:
        engine = effective_translate_engine(
            {"translate_engine": "whisper", "target_language": "ru"}
        )
        self.assertEqual(engine, "argos")
        options, effective = transcribe_options(
            {"translate_engine": "whisper", "target_language": "ru", "language": "en"}
        )
        self.assertEqual(effective, "argos")
        self.assertEqual(options["task"], "transcribe")

    def test_argos_en_ru_transcribes_first(self) -> None:
        options, engine = transcribe_options(
            {
                "translate_engine": "argos",
                "language": "en",
                "target_language": "ru",
            }
        )
        self.assertEqual(engine, "argos")
        self.assertEqual(options["task"], "transcribe")
        self.assertEqual(options["language"], "en")

    def test_off_engine_transcribes(self) -> None:
        options, engine = transcribe_options(
            {"translate_engine": "off", "language": "en"}
        )
        self.assertEqual(engine, "off")
        self.assertEqual(options["task"], "transcribe")

    def test_translate_mode_skips_logprob_by_default(self) -> None:
        cfg = publish_filter_cfg({"translate_engine": "whisper"})
        self.assertTrue(cfg.get("skip_logprob_filter"))

    def test_translate_mode_can_keep_logprob_when_disabled(self) -> None:
        cfg = publish_filter_cfg(
            {
                "translate_engine": "whisper",
                "translate_skip_logprob": False,
                "min_avg_logprob": -0.75,
            }
        )
        self.assertFalse(cfg.get("skip_logprob_filter"))
        self.assertEqual(cfg["min_avg_logprob"], -2.0)

    def test_mqtt_payload_includes_translation_fields(self) -> None:
        meta = {
            "task": "transcribe",
            "translate_engine": "argos",
            "source_language": "en",
            "target_language": "ru",
            "language": "en",
            "original_text": "hello wall",
        }
        payload = build_mqtt_payload("привет стена", meta, ttl=30, color=[255, 255, 255])
        self.assertEqual(payload["text"], "привет стена")
        self.assertEqual(payload["original_text"], "hello wall")
        self.assertEqual(payload["target_language"], "ru")

    def test_unknown_engine_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_translate_engine({"translate_engine": "unknown"})



class Ct2EngineTests(unittest.TestCase):
    """The ct2 engine: config resolution plus the sentence buffer it relies on.

    Deliberately free of ctranslate2/sentencepiece -- mt_ct2 imports those lazily
    so the buffering logic can be tested anywhere.
    """

    def test_ct2_is_a_post_asr_engine(self):
        cfg = {"translate_engine": "ct2", "language": "ru", "target_language": "en"}
        self.assertEqual(effective_translate_engine(cfg), "ct2")
        # ct2 translates after ASR, so Whisper must transcribe, not translate
        options, engine = transcribe_options(cfg)
        self.assertEqual(engine, "ct2")
        self.assertEqual(options["task"], "transcribe")

    def test_flush_is_a_noop_for_engines_that_do_not_buffer(self):
        for engine in ("off", "whisper", "argos"):
            cfg = {"translate_engine": engine, "language": "ru", "target_language": "en"}
            self.assertEqual(flush_pending_translation(cfg), [])

    def test_missing_model_publishes_source_text_instead_of_raising(self):
        # Raising would leave the chunk without a .done file and crash-loop the service.
        cfg = {
            "translate_engine": "ct2",
            "language": "auto",
            "target_language": "en",
            "ct2": {"models_dir": "/nonexistent"},
        }
        text = "Hej verden."
        self.assertEqual(
            apply_post_translation_ex(text, cfg, source_language="da"), (text, text)
        )

    def test_auto_detect_flushes_every_source_language(self):
        cfg = {
            "translate_engine": "ct2",
            "language": "auto",
            "target_language": "en",
            "ct2": {"max_hold_seconds": 60},
        }

        class FakePair:
            def translate(self, text):
                return text.upper()

        saved_buffers = dict(mt_ct2._BUFFERS)
        with mock.patch.object(mt_ct2, "get_translator", return_value=FakePair()):
            try:
                mt_ct2._BUFFERS.clear()
                apply_post_translation_ex("привет мир", cfg, source_language="ru")
                apply_post_translation_ex("привіт світ", cfg, source_language="uk")
                self.assertEqual(flush_pending_translation(cfg), [])   # not stale yet
                released = sorted(flush_pending_translation(cfg, force=True))
            finally:
                mt_ct2._BUFFERS.clear()
                mt_ct2._BUFFERS.update(saved_buffers)
        self.assertEqual(
            released,
            [("ru", "ПРИВЕТ МИР", "привет мир"), ("uk", "ПРИВІТ СВІТ", "привіт світ")],
        )

    def test_split_sentences_keeps_the_trailing_fragment_separate(self):
        complete, remainder = split_sentences("Привет мир. Как дела? Это непол")
        self.assertEqual(complete, ["Привет мир.", "Как дела?"])
        self.assertEqual(remainder, "Это непол")

    def test_split_sentences_handles_closing_punctuation(self):
        complete, remainder = split_sentences('He said "stop!" Then left.')
        self.assertEqual(remainder, "")
        self.assertEqual(len(complete), 2)

    def test_buffer_holds_a_fragment_until_it_is_completed(self):
        buf = SentenceBuffer()
        self.assertEqual(buf.add("Насекомые были первыми"), "")
        self.assertEqual(buf.add("животными воздуха."), "Насекомые были первыми животными воздуха.")

    def test_buffer_releases_a_fragment_once_it_is_too_long(self):
        buf = SentenceBuffer(max_hold_chars=20)
        self.assertEqual(buf.add("a" * 25), "a" * 25)

    def test_buffer_reports_staleness_only_after_the_hold_expires(self):
        buf = SentenceBuffer(max_hold_seconds=0.05)
        self.assertFalse(buf.stale())          # nothing held
        buf.add("fragment with no end")
        self.assertFalse(buf.stale())          # held, but not yet expired
        time.sleep(0.06)
        self.assertTrue(buf.stale())
        self.assertEqual(buf.flush(), "fragment with no end")
        self.assertFalse(buf.stale())          # emptied by the flush

    def test_buffer_flush_is_idempotent(self):
        buf = SentenceBuffer()
        buf.add("trailing words")
        self.assertEqual(buf.flush(), "trailing words")
        self.assertEqual(buf.flush(), "")

    def test_empty_chunk_does_not_look_up_a_model(self):
        cfg = {"translate_engine": "ct2", "target_language": "en", "ct2": {}}
        with mock.patch.object(mt_ct2, "get_translator", side_effect=AssertionError) as lookup:
            self.assertEqual(mt_ct2.translate_buffered("  ", "ar", "en", cfg), ("", ""))
        lookup.assert_not_called()

    def test_languages_linked_to_one_shared_model_load_it_once(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp)
            shared = models / "opus-ROMANCE-en-int8"
            shared.mkdir()
            (shared / "model.bin").write_bytes(b"")
            for lang in ("pt", "ro"):
                (models / f"opus-{lang}-en-int8").symlink_to(shared.name)
            cfg = {"ct2": {"models_dir": str(models)}}
            saved = (dict(mt_ct2._TRANSLATORS), dict(mt_ct2._BY_MODEL), set(mt_ct2._MISSING))
            with mock.patch.object(mt_ct2, "Ct2Pair", side_effect=lambda *a: mock.Mock(beam=2, tokenizer="t")) as ctor:
                try:
                    for store in (mt_ct2._TRANSLATORS, mt_ct2._BY_MODEL, mt_ct2._MISSING):
                        store.clear()
                    pt = mt_ct2.get_translator("pt", "en", cfg)
                    ro = mt_ct2.get_translator("ro", "en", cfg)
                finally:
                    for store, old in zip((mt_ct2._TRANSLATORS, mt_ct2._BY_MODEL, mt_ct2._MISSING), saved):
                        store.clear()
                        store.update(old)
        self.assertIs(pt, ro)
        self.assertEqual(ctor.call_count, 1)

    def test_collapse_repeats_caps_a_runaway_word(self):
        text = "We don't laugh for, " + "for, " * 20 + "for"
        self.assertEqual(collapse_repeats(text), ("We don't laugh for, for, for...", True))

    def test_collapse_repeats_caps_a_runaway_phrase_and_keeps_what_follows(self):
        text = "and buses " * 6 + "with you"
        self.assertEqual(collapse_repeats(text), ("and buses and buses and buses... with you", True))

    def test_collapse_repeats_leaves_a_normal_refrain_alone(self):
        text = "Don't let go, don't let go, don't let go of me."
        self.assertEqual(collapse_repeats(text), (text, False))

    def test_silent_chunk_releasing_held_text_is_judged_on_that_text(self):
        cfg = {
            "translate_engine": "ct2",
            "language": "ru",
            "target_language": "en",
            "ct2": {"max_hold_seconds": 0.05},
        }

        class FakePair:
            def translate(self, text):
                return text.upper()

        def fake_model(text):
            segment = mock.Mock(text=text, no_speech_prob=0.0, avg_logprob=-0.1)
            info = mock.Mock(language="ru", language_probability=0.9)
            return mock.Mock(transcribe=lambda *a, **k: ([segment] if text else [], info))

        saved_buffers = dict(mt_ct2._BUFFERS)
        with mock.patch.object(mt_ct2, "get_translator", return_value=FakePair()):
            try:
                mt_ct2._BUFFERS.clear()
                _, _, _, meta = transcribe(fake_model("и танцем как он"), Path("a.wav"), cfg)
                self.assertTrue(meta.get("buffered"))
                time.sleep(0.06)
                display, source, _, _ = transcribe(fake_model(""), Path("b.wav"), cfg)
            finally:
                mt_ct2._BUFFERS.clear()
                mt_ct2._BUFFERS.update(saved_buffers)
        self.assertEqual((display, source), ("И ТАНЦЕМ КАК ОН", "и танцем как он"))

if __name__ == "__main__":
    unittest.main()
