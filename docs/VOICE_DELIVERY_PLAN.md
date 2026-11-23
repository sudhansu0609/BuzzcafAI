# Voice delivery: spacing, tempo, mood, dramatic moments (2026-10-23)

User asks (2026-10-23): his cloned narration needs more space and timing between
words; he wants to control spacing, tempo and mood from the Story Desk; and the
tool should decide where dramatic narration goes.

Voice reference now: `BuzzEdit/data/voices/sudhansu.wav` = 40 s (18:19 + 8:51 of
his 30-min recording). He preferred it at Chatterbox defaults
(exaggeration 0.5, cfg_weight 0.5, temperature 0.8). The tts venv runs torch
2.7.1+cu128 on the GPU since today.

## Contract: `style` (BuzzEdit `POST /api/narration/synthesize`, field `style`)

All keys optional. Resolution: engine defaults <- mood preset <- explicit keys.

| key | range | default | meaning |
|---|---|---|---|
| `mood` | preset id | `"steady"` | a preset from `GET /api/narration/moods` |
| `exaggeration` | 0-2 | 0.5 | Chatterbox expressiveness |
| `cfg_weight` | 0-1 | 0.5 | lower = slower, more deliberate pacing |
| `temperature` | 0.1-1.5 | 0.8 | lower = steadier, less random |
| `pace` | 0.5-2 | 1.0 | time-stretch of spoken audio |
| `word_gap_ms` | 0-300 | 0 | extra silence added inside each detected short gap between words |
| `phrase_pause_s` | 0-2 | 0 | extra silence added at each detected natural pause (comma-length) |
| `sentence_pause_s` | 0-3 | 0 | silence between sentences (each sentence its own batch when > 0) |

`GET /api/narration/moods` -> `{"moods": [{id, label, description, style:{...}}]}`.
Presets (engine is the single source; tune by ear). `phrase_pause_s`/`sentence_pause_s` are
*additions* to the model's own pauses (`space_out`'s comma-/sentence-length quiet-run detection,
and the gap `insert_sentence_pauses` puts between batches) rather than replacements, so they were
halved from the first cut of these numbers (V1 listening test, E3):

| id | label | exaggeration | cfg | temp | pace | word_gap_ms | phrase_pause_s | sentence_pause_s |
|---|---|---|---|---|---|---|---|---|
| steady | Steady storyteller (default) | 0.5 | 0.5 | 0.8 | 0.95 | 40 | 0.125 | 0.225 |
| calm | Calm, relaxed | 0.35 | 0.35 | 0.6 | 0.9 | 60 | 0.175 | 0.3 |
| warm | Warm, conversational | 0.55 | 0.5 | 0.8 | 1.0 | 20 | 0.075 | 0.15 |
| eerie | Slow and eerie | 0.4 | 0.3 | 0.6 | 0.85 | 80 | 0.25 | 0.4 |
| dramatic | Dramatic | 0.8 | 0.4 | 0.8 | 0.95 | 40 | 0.15 | 0.3 |
| intense | Intense, urgent | 1.0 | 0.5 | 0.8 | 1.05 | 0 | 0.05 | 0.125 |

## Contract: inline delivery cues (in the text)

Existing: `(pause)`, `(pause Ns)`, `(beat)`, `(slow)`, `(normal)`.
New: `(dramatic)`, `(intense)`, `(soft)`, `(calm)` switch the delivery of what
follows until `(normal)` (which also ends `(slow)`). None is spoken. Each switches
to that cue's settings layered on the base style:

| cue | exaggeration | cfg | pace factor | before it |
|---|---|---|---|---|
| (dramatic) | 0.85 | 0.4 | x0.95 | 0.3 s silence |
| (intense) | 1.0 | 0.5 | x1.05 | none |
| (soft) | 0.3 | 0.35 | x0.9 | 0.2 s |
| (calm) | 0.35 | 0.35 | x0.92 | none |

Spacing keys (`word_gap_ms`, pauses) stay those of the base style.

## Studio side

- Story Desk "Voice and delivery" panel per channel: mood preset, sliders for
  tempo (pace), word spacing, comma pause, sentence pause, expressiveness,
  steadiness (temperature), dramatic moments (`off` / `subtle` / `strong`), and a
  Preview (sample line or own text -> plays in the page). Saved in auto_story
  settings as `voice_style[channel]`; every auto-story narration sends it as `style`.
- `dramatic` level goes to NarrationDirector: `off` = no mood cues, `subtle` =
  only at the reveal / climax / final line (<= ~10% of sentences), `strong` = also
  rising tension and rule statements (<= ~25%).

## Status

| # | item | owner | state |
|---|---|---|---|
| E1 | engine: style keys, moods, gap insertion, sentence pauses, mood cues, tests | BuzzEdit implementer | done |
| E2 | `GET /api/narration/moods` + style validation in audio/narration.py | BuzzEdit implementer | done |
| S1 | auto_story `voice_style` settings + style passed to narration + preview API | Studio implementer | done |
| S2 | Story Desk "Voice and delivery" panel + preview player, frontend built | Studio implementer | done |
| S3 | NarrationDirector: mood cues + dramatic level | Studio implementer | done |
| V1 | listening test of presets on his voice, tune numbers | main session | pending |
| E3 | babble guard + spacing fix | BuzzEdit implementer | done |
| E4 | Whisper-verified batches | BuzzEdit implementer | done |

### E4: Whisper-verified batches (2026-10-23)

The length-based babble guard (E3) judged by chars/pace, not by what was actually said: in
"eerie"/"dramatic" (slower, longer pauses) a 3-sentence batch was judged too long and cut at the
last long pause, dropping the batch's real final sentence. Every chatterbox batch (hi/en) is now
transcribed by a local `faster-whisper` (`large-v3-turbo`/cuda/fp16, falling back to
int8_float16 then CPU `small`/int8) and scored against its own script text (fuzzy word match,
order-preserving): coverage < 0.85 regenerates (up to 3 extra attempts, best kept); more than 1
word heard past the last matched one is cut there (never inside matched speech), not by length.
Kokoro is not checked (it does not hallucinate); if the verifier cannot load, chatterbox falls
back to the old length guard with cutting disabled (regenerate only). `engines/tts/cli.py`'s
result carries `verify: {engine, batches, regenerated, cut, min_coverage, flagged}` in place of
the old `babble_fixes` count; `backend/audio/narration.py` passes it through unchanged.
`faster-whisper` installed into `engines/tts/.venv` without touching its torch (2.7.1+cu128).
Verified: all six moods on the real "eerie"/"dramatic" repro text, each independently
re-transcribed (BuzzEdit's own venv Whisper) with all six sentences present and nothing extra;
`backend/tests/test_narration.py` + `test_narration_style.py` (92 pass, 14 new).

## Voice match: seed-vc fine-tuned on his recordings (2026-10-23)

He judged the horror intonation of the grave-reference samples good but the voice
not his. Speaker similarity (Chatterbox voice encoder, mean vs two held-out clips of
his ep2/ep3 narration, which score 0.947 against each other): Chatterbox clones
0.78-0.86; through the stock seed-vc with a 25 s ep3 target 0.85-0.86. Plan: fine-tune
seed-vc on ~40-60 min of his own narration and convert every Chatterbox narration
with it (intonation from Chatterbox, timbre from the fine-tuned model).

| # | item | owner | state |
|---|---|---|---|
| F1 | dataset: his clean narration sliced into 3-15 s clips (holdouts excluded) | implementer | done |
| F2 | fine-tune run (seed-vc train.py, the converter's own model config) | implementer | done |
| F3 | `engines/seedvc/cli.py convert` can load a fine-tuned checkpoint + config | implementer | done |
| F4 | evaluation: similarity + transcript on converted horror samples | implementer | done (no clear gain yet, see below) |

### F2-F4 result (2026-10-23)

1300-step fine-tune (batch 8, config_dit_mel_seed_uvit_whisper_small_wavenet.yml, ~33 min GPU,
loss 0.67 -> 0.574) did **not** clearly beat stock seed-vc on speaker similarity against the two
held-out clips: stock 0.845-0.860 (avg 0.852) vs. the final checkpoint 0.839-0.846 (avg 0.842) on
the four horror test sources. The trend across checkpoints is monotonic (step500 avg 0.831 ->
step1000 0.839 -> step1300 0.842) but still short of stock within the ~45 min budget -- more
steps may close the gap, out of scope here. Words survived the fine-tuned conversion in all four
Whisper checks. `engines/seedvc/cli.py convert` can load a fine-tuned checkpoint (explicit
--params or a voice's `.seedvc.json` sidecar) and swap back to stock cleanly, verified live
through `serve` (34 tests pass in `test_seedvc.py`, 4 new).

### Round 2 (2026-10-23 evening): more steps, slower

He picked 4 (and maybe 3) fine-tuned as closest; asked for more similar and slower. Slower without
time-stretch: seed-vc `length_adjust` 1.15 / 1.3 (regenerates the mel at the new length) and two
slower Chatterbox sources (6: exag 0.3, cfg 0.2, temp 0.6, gaps 90 ms / 0.4 s / 0.8 s; 7: exag 0.25,
cfg 0.2, temp 0.55, gaps 110 ms / 0.5 s / 1.0 s; ref_grave). A 2000-step continuation
(`skinWalker/vendor/seed-vc/runs/sudhansu_r2`) was killed at 1610 by low RAM (LM Studio loaded
Gemma 12B with mlock for BuzzAnimate); its step-1500 checkpoint (2800 total) scored 0.834 on 4 vs
0.842 for the 1300-step model, length_adjust 1.15/1.3 gave 0.839/0.842, words intact. Samples:
Desktop `Voice samples\Horror test\trained_voice_2`.

| # | item | owner | state |
|---|---|---|---|
| F5 | round-2 samples (more steps, length_adjust, slower sources) | main session | done |
| F6 | `runs/sudhansu_r3`: 1500 more steps from r2 step 1500, eval each 500-step save | main session | done: 3800 steps 0.824 / 0.843 (30% slower), 4300 steps 0.836 / 0.842 -- plateau ~0.84 |

### Round 4: his picks, speed, clean stops (2026-10-23 evening)

He picked `4_3800steps` (normal) and `4_4300steps_slowest` but 10% faster (length_adjust 1.3 -> 1.18).
Kept: BuzzEdit `data/voice_training/runs/sudhansu/ft_3800steps.pth`, `ft_4300steps.pth`.
New test line with `!` and `?` (scratchpad `voice/horror2.txt`). Measured: seed-vc shortens every
pause by ~0.3 s (Chatterbox 1.06/0.96/1.08 s -> 0.66/0.60/0.82 s) and leaves a -70 dB floor in
them; re-imposing the Chatterbox source's silences on the conversion (times x length_adjust,
30 ms margins, 15 ms fades; scratchpad `voice/gate.py`) restores them exactly with no word lost.
Whisper word accuracy 0.864 converted vs 0.886 Chatterbox-only: the gap is हवेली heard हवीली;
अकेला -> अखेला and राठौड़ -> राठोर happen in Chatterbox too; the rest are spelling variants.
diffusion_steps 80 vs 40: no measurable difference.

| # | item | owner | state |
|---|---|---|---|
| F7 | round-4 samples: picks, length_adjust 1.18, clean stops, ! and ? line | main session | done |
| F8 | wire into narration: seed-vc convert (fine-tuned) + source-silence gate + length_adjust setting; Horror narrator mood | implementer | done: `sudhansu_horror.seedvc.json` (convert_after) + `audio/silence_gate.py` + `narration.synthesize`'s convert_after path (Chatterbox at pace 1.0, seed-vc length_adjust = 1/pace, then the gate) + `horror_narrator` mood wired into BuzzEdit; Raat3Baje/Beyond3Baje default to both in Studio auto_story (a saved per-channel choice still wins); 136 BuzzEdit + 14 Studio tests pass. Real run (`horror2.txt`, `sudhansu_horror`, mood horror_narrator): duration 23.99 s, length_adjust 1.176, word_accuracy 0.841, sim 0.8557, gap floor -141 dB under speech (seed-vc's own floor was -70 dB before the gate) -- all in the expected range; `scratchpad/voice/listen/horror_r5/9_pipeline_horror_narrator.wav` |
