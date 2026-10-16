# Whisper pipeline (Pi5 capture + Q6A inference)

Record from ReSpeaker (Pi5) → forward chunks → transcribe on the offload host
(Whisper on the Radxa Q6A's Hexagon NPU, or faster-whisper on CPU) → translate
→ publish to MQTT `whisper/transcript`.

Source repo: [whisper-audio-capture](https://github.com/kaerka/whisper-audio-capture)
(deployed to `/data/spectra/repos/whisper-audio-capture`).

## Services

| Unit | Role |
|------|------|
| `spectra-whisper-capture` | `record_respeaker_v2.py` → `/data/spectra/audio-capture/chunks` |
| `spectra-whisper-transcribe` | Watch chunks, ASR, translate, MQTT publish |

Config: `/data/spectra/config/whisper.local.json` (from `config.example.json`, or
`config.npu.example.json` for the NPU path).

## ASR engine

| `engine` | Status |
| --- | --- |
| `cpu` | faster-whisper (Pi5-local fallback; Q6A before 2026-10-01) |
| `npu` | **Q6A default** — Whisper small (w8a16) on the Hexagon V68 NPU |
| `coral` | Stub — not implemented |
| `remote` | Stub — not implemented |

### `npu` — Hexagon DSP on the Radxa Dragon Q6A

`asr_npu.py` drives `whisper-npu-host` (`npu_host/`), a persistent helper process
holding one FastRPC session open. It must be persistent: initialising the model
costs ~0.9s, and a process killed mid-run leaks one of the DSP's 12 compute
contexts. Once they are exhausted the DSP wedges so badly that the board needs
a power cycle. The helper always releases its session, including on SIGTERM.

Measured on 40 FLEURS Russian clips (476s of read speech):

| | `npu` (Hexagon V68) | `cpu` (faster-whisper small/int8, 8 threads) |
| --- | ---: | ---: |
| Compute | 84.2s | 963.4s |
| Speed | **5.65x realtime** | 0.49x realtime |
| Mean latency per clip | **2.1s** | 24.1s |
| WER | 14.6% | 9.2% |
| CER | 4.9% | 2.7% |

The NPU is 11.4x faster for ~5 points of WER. The CPU's better accuracy is not
reachable live, since 0.49x realtime means it never catches up with the audio.

Two caveats on the quality gap: 3 of 40 clips write digits where the reference
spells numbers out, and 7 of 40 switch to Latin script on proper nouns. Excluding
those artefacts the gap narrows to 12.0% vs 8.0%, so most of it is genuine
quantisation loss.

The SDK supports 99 languages and auto-detects by default (`language: auto`).
Its own `translate` task returns nothing on this quantised model, so the NPU
engine always transcribes and translation is done by `ct2` afterwards.

The SDK reports no per-segment confidence, so `no_speech_prob` and `avg_logprob`
are absent on this path: the publish filter falls back to the SDK's own VAD plus
the word-count and phrase-blocklist rules (see **Publish filters**).

## Translation

| `translate_engine` | `target_language` | Behavior |
| --- | --- | --- |
| `ct2` | `en` (any pair with a model) | **Q6A default** — transcribe, then CTranslate2 opus-mt |
| `whisper` | `en` | faster-whisper `task=translate` (cpu engine only) |
| `argos` | e.g. `ru` | Transcribe then Argos (e.g. en→ru for future use) |
| `off` | — | Transcribe only, no translation |

### `ct2` — CTranslate2 NMT

`mt_ct2.py`, int8 opus-mt. Two measurements shaped it:

- **Thread placement dominates.** On the Q6A's big.LITTLE layout, spreading
  CTranslate2 over all 8 cores is **8.6x slower** than 2 threads pinned to the
  four Cortex-A78s, because the A78s stall on the A55s. Hence the default
  `intra_threads: 2` and the pinning done at startup.
- **Fragments translate worse than sentences.** Splitting one sentence in two
  costs **3.6 BLEU**. So text is held to sentence boundaries before translating.

ru→en, beam 2, 2 threads on A78: **21.9 BLEU / 51.8 chrF at 0.61s per sentence**.
Beam 1 is 0.52s for 21.0 BLEU; beam 4 is slower *and* slightly worse. Translating
the clean reference text instead of ASR output scores 28.4 BLEU, so ASR error
costs ~7 BLEU downstream. NLLB-200-distilled-600M reaches 25.2 BLEU but needs
5.7s per sentence — too slow to use here.

Tokenisation uses `sentencepiece` directly, so the service venv needs only
`ctranslate2` + `sentencepiece` — no torch or transformers. Models live in
`/data/spectra/models/mt` and are converted by Ansible (`whisper_ct2_pairs`);
by hand:

```bash
ct2-transformers-converter --model Helsinki-NLP/opus-mt-ru-en \
  --output_dir /data/spectra/models/mt/opus-ru-en-int8 --quantization int8 \
  --copy_files source.spm target.spm
```

Whisper still auto-detects the spoken language; the bridge then picks
`opus-<lang>-en-int8`, and a language with no model is published untranslated.
The default deploy covers 21 languages. Some languages (Portuguese, Romanian,
Hebrew, Greek) have no dedicated `opus-mt-xx-en` model; to add them, list a
multi-source model (`ROMANCE-en`, `sem-en`, `grk-en`) in
`whisper_ct2_shared_models`, which converts it once and links each language to
it. The bridge loads a shared model once.

`get_translator` looks for `opus-{src}-{tgt}-int8`, `opus-mt-{src}-{tgt}-int8`,
`{src}-{tgt}`, then `nllb600-int8`. A detected language with no model is
published untranslated, with one warning per pair in the journal.

**Sentence buffering.** A chunk ending mid-sentence publishes nothing; the
fragment is held and emitted with the chunk that completes it. The held text is
released anyway once `max_hold_seconds` (6s) or `max_hold_chars` (400) is
exceeded, including when no further audio arrives at all — so a speaker who
trails off still gets output. Buffered chunks still get their `.txt`/`.meta.json`
/`.done` audit files, with `"buffered": true` in the metadata.

### `whisper` — faster-whisper translate (cpu engine)

Runs **per audio chunk** (default **10s** capture). Code-switching mid-chunk
(e.g. English then Russian in one clip) may garble; each new chunk re-detects
language. With `target_language: en`:

- Set `language` to `auto` (default).
- Publish filter **skips logprob** by default (`translate_skip_logprob: true`); still
  applies min word count, phrase blocklist, and `no_speech_prob`.

## Offload host (Radxa Q6A — default since 2026-07-08)

Inference runs on **spectra-offload** (Radxa Dragon Q6A, QCS6490): capture
stays on the Pi5; a forwarder pushes fresh chunks over the `your matrix ethernet subnet` link;
the Q6A transcribes, translates and publishes straight to Pi5 Mosquitto.

```
Pi5: spectra-whisper-capture → chunks → spectra-whisper-forward (rsync loop)
Q6A: spectra-whisper-transcribe (Hexagon NPU + ct2) → MQTT whisper/transcript → walls
```

| Unit | Host | Role |
|------|------|------|
| `spectra-whisper-forward` | Pi5 | `forward_chunks.sh` — rsync fresh chunks (5 min window) every 2s |
| `spectra-whisper-transcribe` | Q6A | same `transcribe_watch.py`, `engine: npu` |

Pi5-local `spectra-whisper-transcribe` is **disabled** (fallback: re-enable it and
stop the forwarder). Bootstrap a new offload host with
`scripts/bootstrap_offload_host.sh`, add it to the `whisper_offload` inventory
group, then `ansible-playbook playbooks/whisper-offload.yml`. With the default
`whisper_offload_engine: npu`, first complete **Deploying the NPU path** below.
To run the Q6A on its CPU instead, set `whisper_offload_engine: cpu` and
`whisper_translate_engine: whisper` for the host.

### Deploying the NPU path

The `whisper_npu` role (pulled in by `whisper_offload`) automates the board
setup; three things must be in place before it runs.

1. **Radxa's FastRPC stack**, not Canonical's. Install `fastrpc` and
   `libcdsprpc1` from Radxa's repo, plus `qairt-dsp-binaries` (Qualcomm PPA)
   for the QNN DSP skels. **Never install `libqnn1` or `qairt-libs`**: apt
   resolves them by removing Radxa's `fastrpc` in favour of Canonical's
   `qcom-fastrpc1`, which is built for a different kernel and breaks every
   FastRPC call. The role unpacks the `qairt-libs` .deb it needs instead of
   installing it. The role asserts these packages are present.
2. **The Qualcomm VoiceAI ASR SDK** (2.3.0.0) at
   `/data/spectra/vendor/voiceai_asr/2.3.0.0/whisper_sdk`.
3. **The Whisper-Small-Quantized model** (Qualcomm AI Hub; `encoder_model_htp.bin`,
   `decoder_model_htp.bin`, `vocab.bin`, `speech_float.eai`) at
   `/data/spectra/vendor/whisper_models/ai_hub_small_quantized`.

Items 2 and 3 are proprietary and stay out of git. The role stops with a list of
anything missing. Then it:

- installs the device-tree overlay that gives FastRPC its reserved DMA pool
  (`qcs6490-radxa-dragon-q6a-fastrpc-dma`) and adds it to the boot entry;
- boots the CDSP at startup (`dsp-remoteproc.service` — the PAS remoteproc does
  not auto-boot) and orders `cdsprpcd` after it;
- merges the QNN V68 skels into Radxa's DSP payload and adds the
  version-suffixed names QNN requests;
- grants the `fastrpc` group the `*-secure` device nodes (Radxa leaves them
  root-only, and the client library segfaults on `EACCES`) and adds `spectra`;
- unpacks `qairt-libs` at the installed `qairt-dsp-binaries` version into
  `/data/spectra/opt/qairt-libs`;
- builds `whisper-npu-host` as `spectra` into `/data/spectra/opt/whisper-npu-host`
  and smoke-tests it as `spectra`.

**First deploy on a fresh board: reboot afterwards.** The overlay only takes
effect at boot; the role prints a warning while it is not yet live.

Helper stderr goes to `/data/spectra/logs/whisper-npu-host.log`. The SDK also
prints diagnostics on stdout, which `asr_npu.py` skips.

### Purge queue + clock skew

Orchestrator **Purge queue** deletes pending audio only (no matching
`transcripts/*.done`). Finished `.wav` files remain — chunk directory size ≠
queue depth.

If Pi5 **chrony/NTP is down** and the clock drifts (or jumps), the forwarder’s
`find -mmin -5` window can match hundreds of *old* chunks (future-dated mtimes
relative to a stuck “now”). Purge then appears to fail: queue drops and climbs
back as those files are re-rsynced to Dragon. Check `timedatectl` /
`systemctl status chronyd` on the Pi5, fix time, purge again. See CONTEXT
(see project history).

## Latency

Per 10s chunk, int8:

| Host | Engine / model | Per chunk | End-to-end |
| --- | --- | ---: | ---: |
| Pi5 CPU (old default) | cpu / base, whisper translate | 15–30s | ~20–40s |
| Q6A CPU | cpu / small, whisper translate | ~10s | ~15–20s |
| Q6A CPU | cpu / base, whisper translate | ~4s | ~10–15s |
| **Q6A NPU** | **npu + ct2 ru→en** | **~2.5–4s** | **~13–15s** |

On the NPU path most of the remaining latency is the 10s capture chunk itself,
plus the sentence buffer (0–6s) when a chunk ends mid-sentence. Compute is no
longer the bottleneck and uses roughly 2.3 of the Q6A's 8 cores.

`whisper-npu-host --stream` removes the chunk floor. It reads live 16 kHz PCM
and emits each utterance as the SDK's VAD closes it: worst case **0.8s** after
speech ends, and 9 of 13 results arrived while the speaker was still talking.
Using it needs live audio on the Q6A rather than forwarded files — a capture
side change, not yet done.

All accuracy figures above come from FLEURS read speech — clean studio audio in
full sentences. Real room audio will be worse. 40 clips is enough to choose an
architecture, not to put a tight confidence interval on it.

Q6A CPU notes: 4×A55 + 4×A78; default thread count beats forcing 8 threads
(big.LITTLE); `beam_size` default (5) is fine — greedy is not reliably faster.

Optional **English → Russian** (future):

```json
"translate_engine": "argos",
"language": "en",
"source_language": "en",
"target_language": "ru"
```

(`translate_engine: whisper` with `target_language: ru` auto-falls back to Argos.)

To disable translation:

```json
"translate_engine": "off",
"language": "en"
```

## Publish filters

Typing, keyboard clicks, and silence often produce low-confidence Whisper
hallucinations. Those are still written to the transcripts dir for audit, but
**not** published to MQTT unless they pass:

- VAD + raised `no_speech_threshold` (default 0.65)
- Minimum word/character counts
- Average segment `no_speech_prob` (logprob skipped in translate mode by default)
- Known hallucination phrase blocklist

With `engine: npu` the confidence rules do not apply — the VoiceAI SDK exposes no
per-segment probabilities — so rejection rests on its VAD and the word-count and
blocklist rules.

Tune via `/data/spectra/config/whisper.local.json` (`min_words`, `max_no_speech_prob`, etc.).

## Deploy

```bash
cd ansible
# Pi5 capture (+ local transcribe fallback)
ansible-playbook playbooks/controller.yml -i inventory/hosts.yml
# Q6A offload host (NPU + ct2) and the Pi5 forwarder
ansible-playbook playbooks/whisper-offload.yml -i inventory/hosts.yml
```

## Manual test

```bash
# Publish a fake transcript (skips ASR)
mosquitto_pub -h 127.0.0.1 -t whisper/transcript \
  -m '{"text":"hello wall","ttl":15,"color":[255,255,255]}'

# Watch services
journalctl -u spectra-whisper-capture -f
journalctl -u spectra-whisper-transcribe -f

# NPU helper directly, on the Q6A as spectra (one wav path per line on stdin)
. /data/spectra/opt/whisper-npu-host/env.sh
echo /path/to/16k-mono.wav | /data/spectra/opt/whisper-npu-host/bin/whisper-npu-host \
  --model /data/spectra/vendor/whisper_models/ai_hub_small_quantized --serve-files
```

Never `kill -9` the helper: each unclean exit leaks a DSP session (12 total).
Close its stdin or send SIGTERM.

## Local unit tests

```bash
cd bridges/whisper
python3 -m unittest test_translate.py
```
