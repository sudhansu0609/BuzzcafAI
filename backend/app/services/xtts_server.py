"""
MidnightBuzz XTTS v2 Persistent Microservice
Loads XTTS v2 once at startup and stays alive on port 8096.
The main backend calls http://localhost:8096/synthesize instead of spawning subprocesses.
"""
import os
import sys
import io
import uuid
import torch

# Force UTF-8 stdout on Windows to avoid emoji encode errors
if sys.stdout.encoding != 'utf-8':
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)
if sys.stderr.encoding != 'utf-8':
    sys.stderr = open(sys.stderr.fileno(), mode='w', encoding='utf-8', buffering=1)

# Patch torch.load for PyTorch 2.6 compatibility
_orig_load = torch.load
def _patched_load(*args, **kwargs):
    kwargs["weights_only"] = False
    return _orig_load(*args, **kwargs)
torch.load = _patched_load

# Patch torchaudio to use soundfile backend
import torchaudio
import soundfile as sf
def _patched_ta_load(filepath, **kwargs):
    data, sr = sf.read(filepath)
    if len(data.shape) == 1:
        tensor = torch.from_numpy(data).float().unsqueeze(0)
    else:
        tensor = torch.from_numpy(data.T).float()
    return tensor, sr
torchaudio.load = _patched_ta_load

os.environ["COQUI_TOS_AGREED"] = "1"

import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json
import tempfile

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VOICES_DIR = os.path.join(BACKEND_DIR, "uploads", "voices")
PORT = 8096

# ── Single-instance guard ───────────────────────────────────────────────────
# If another XTTS server is already serving on this port, exit NOW — before
# loading the ~2GB model. Windows' default SO_REUSEADDR lets multiple servers
# bind the same port, and every duplicate loads another copy of the model into
# VRAM until the GPU is exhausted and everything slows to a crawl.
import urllib.request as _urlreq
try:
    with _urlreq.urlopen(f"http://localhost:{PORT}/health", timeout=2) as _r:
        if _r.status == 200:
            print(f"[XTTS Server] Already running on port {PORT} — exiting to avoid a duplicate model load.")
            sys.stdout.flush()
            sys.exit(0)
except SystemExit:
    raise
except Exception:
    pass  # nothing listening → we are the first instance, continue

use_gpu = torch.cuda.is_available()
print(f"[XTTS Server] Loading XTTS v2 model (GPU={use_gpu})...")
sys.stdout.flush()

import re
import time
import numpy as np

from TTS.api import TTS
tts_model = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2", progress_bar=False, gpu=use_gpu)

# Direct handle to the underlying Xtts model so we can precompute & cache
# speaker conditioning latents (the expensive part) instead of re-analyzing
# the reference audio on every single sentence.
XTTS = tts_model.synthesizer.tts_model
OUTPUT_SR = 24000

# repetition_penalty suppresses the mumbling/stuttering XTTS produces at low
# values, but pushing it too high also penalizes the stop token, so the GPT
# rambles past the end of the sentence (worst on short Hindi fragments).
# Overridable per request.
REPETITION_PENALTY = 5.0

print(f"[XTTS Server] ✅ Model loaded! Listening on port {PORT}")
sys.stdout.flush()

TTS_LOCK = threading.Lock()


def _warmup():
    """Run a couple of throwaway inferences so CUDA kernels are compiled and
    cached BEFORE the first real user request. Without this the user's first
    message of a session pays a 6-10s cold-start penalty."""
    try:
        # Build (or reuse) a tiny 3s reference so we can exercise the full path.
        warm_ref = os.path.join(VOICES_DIR, "60sec_ref_12s.wav")
        if not os.path.exists(warm_ref):
            warm_ref = os.path.join(VOICES_DIR, "_warmup_ref.wav")
            t = np.linspace(0, 3, 24000 * 3, endpoint=False)
            tone = (0.1 * np.sin(2 * np.pi * 140 * t)).astype(np.float32)
            sf.write(warm_ref, tone, 24000, subtype='PCM_16', format='WAV')
        g, s = _get_cached_latents(warm_ref)
        for lang, txt in (("en", "This is a warm up sentence."), ("hi", "यह एक टेस्ट वाक्य है।")):
            XTTS.inference(
                text=txt, language=lang, gpt_cond_latent=g, speaker_embedding=s,
                temperature=0.75, repetition_penalty=REPETITION_PENALTY, length_penalty=1.0,
                top_k=50, top_p=0.85, enable_text_splitting=False,
            )
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        print("[XTTS Server] ✅ Warmup complete — first request will be fast.")
        sys.stdout.flush()
    except Exception as e:
        print(f"[XTTS Server] Warmup skipped: {e}")
        sys.stdout.flush()

# Cache: speaker_wav path -> (mtime, gpt_cond_latent, speaker_embedding)
_LATENT_CACHE = {}


def _get_cached_latents(speaker_wav: str):
    """Return (gpt_cond_latent, speaker_embedding) for the reference, computing
    them only once per file and reusing them across all later sentences."""
    try:
        mtime = os.path.getmtime(speaker_wav)
    except OSError:
        mtime = 0
    cached = _LATENT_CACHE.get(speaker_wav)
    if cached and cached[0] == mtime:
        return cached[1], cached[2]
    gpt_cond_latent, speaker_embedding = XTTS.get_conditioning_latents(
        audio_path=speaker_wav,
        gpt_cond_len=30,
        gpt_cond_chunk_len=6,
        max_ref_length=30,
        sound_norm_refs=True,
    )
    _LATENT_CACHE[speaker_wav] = (mtime, gpt_cond_latent, speaker_embedding)
    print(f"[XTTS Server] Cached speaker latents for {os.path.basename(speaker_wav)}")
    sys.stdout.flush()
    return gpt_cond_latent, speaker_embedding


# ── Over-generation guard ───────────────────────────────────────────────────
# XTTS sometimes keeps talking past the end of the text, emitting rambled or
# hallucinated audio. It is stochastic — the same input can render correctly on
# one attempt and run 3x long on the next — and no sampling parameter
# (temperature / top_p / top_k / repetition_penalty) reliably suppresses it.
# It is worst for Hindi, whose text frontend is an unimplemented stub in Coqui
# TTS 0.22.0 (tokenizer.py: `elif lang == "hi": # @manmay will implement this`).
#
# So instead of tuning, we measure: estimate how long the line *should* take,
# then re-roll the take when the result runs long and keep the closest one.
MAX_ATTEMPTS = 2
DURATION_TOLERANCE = 1.35   # accept up to 35% over the estimate
TRUNCATION_FLOOR = 0.55     # below this, the take was cut short — also reject

# Absolute slack added on top of the ratio test. Short lines have very noisy
# duration ratios — "Sure!" overshooting its 1.2s estimate by half a second
# reads as 1.4x and used to burn three full takes for nothing. Re-rolling is
# expensive (every take queues behind the global GPU lock and delays all other
# sentences), so only re-roll when the line is long AND proportionally over.
ABS_SLACK = 1.5

# Hard wall-clock ceiling per sentence. Once exceeded we ship the best take we
# have rather than keep the listener waiting for a marginally better one.
SENTENCE_TIME_BUDGET = 7.0

# Speaking-rate estimates (characters per second), calibrated against Edge TTS
# renders of the same lines. Devanagari packs more phonemes per character than
# Latin, so it reads slower per character.
CPS_DEVANAGARI = 7.0
CPS_LATIN = 13.0
# Lead-in/lead-out breath charged per sentence. Measured: tightening this to
# 0.35 did NOT reduce over-generation (median stayed ~1.27x and the tail got
# worse), because Hindi overruns often enough that all takes get rejected and
# the closest-take fallback kicks in anyway. 0.8 measured better on the tail.
UTTERANCE_OVERHEAD = 0.8


def _expected_duration(text: str) -> float:
    """Roughly how many seconds this line should take to speak."""
    deva = sum(1 for ch in text if 'ऀ' <= ch <= 'ॿ')
    cps = CPS_DEVANAGARI if deva > len(text) * 0.3 else CPS_LATIN
    return UTTERANCE_OVERHEAD + len(text) / cps


def _trim_trailing_silence(wav: np.ndarray, thresh: float = 0.01,
                           keep: float = 0.10) -> np.ndarray:
    """Drop trailing digital silence, leaving a short natural tail."""
    if wav.size == 0:
        return wav
    loud = np.where(np.abs(wav) > thresh)[0]
    if loud.size == 0:
        return wav
    end = min(len(wav), int(loud[-1]) + int(OUTPUT_SR * keep))
    return wav[:end]


def _synthesize_sentence(sent, lang, gpt_cond_latent, speaker_embedding,
                         temperature, speed, repetition_penalty,
                         max_attempts=None):
    """Render one sentence, re-rolling takes that overrun the expected duration.

    Returns (wav, attempts, accepted). Falls back to the closest-to-expected
    take when every attempt overruns, so we always return real audio.

    Re-rolls cost real latency — every take queues behind the global GPU lock,
    delaying every other sentence in the reply — so callers that care about
    time-to-first-audio can pass max_attempts=1 to skip the guard entirely.
    """
    expected = _expected_duration(sent)
    allowed = expected * DURATION_TOLERANCE + ABS_SLACK
    attempts_cap = MAX_ATTEMPTS if max_attempts is None else max(1, int(max_attempts))
    best = None       # (excess_ratio, wav)
    started = time.time()

    for attempt in range(1, attempts_cap + 1):
        _t0 = time.time()
        result = XTTS.inference(
            text=sent,
            language=lang,
            gpt_cond_latent=gpt_cond_latent,
            speaker_embedding=speaker_embedding,
            temperature=temperature,
            repetition_penalty=repetition_penalty,
            length_penalty=1.0,
            top_k=50,
            top_p=0.85,
            speed=speed,
            # We split sentences ourselves, so XTTS's internal splitter stays
            # off — it crashes on Hindi ('hi' missing from its char_limits).
            enable_text_splitting=False,
        )
        _infer_s = time.time() - _t0
        wav = _trim_trailing_silence(np.asarray(result["wav"], dtype=np.float32))
        ratio = (len(wav) / OUTPUT_SR) / expected if expected > 0 else 1.0
        print(f"[XTTS Server]   [t] take {attempt}: infer={_infer_s:.2f}s "
              f"audio={len(wav)/OUTPUT_SR:.2f}s chars={len(sent)} ratio={ratio:.2f}x")
        sys.stdout.flush()

        if best is None or abs(ratio - 1.0) < abs(best[0] - 1.0):
            best = (ratio, wav)

        dur = len(wav) / OUTPUT_SR
        # Accept on the absolute allowance, not the bare ratio: a short line
        # half a second over its estimate is fine, a long line 40% over is not.
        if dur <= allowed and ratio >= TRUNCATION_FLOOR:
            return wav, attempt, True

        if attempt >= attempts_cap:
            break
        if time.time() - started > SENTENCE_TIME_BUDGET:
            print(f"[XTTS Server]   time budget hit — shipping best take "
                  f"({best[0]:.2f}x)")
            sys.stdout.flush()
            return best[1], attempt, False

        print(f"[XTTS Server]   take {attempt} rejected ({dur:.2f}s > "
              f"{allowed:.2f}s allowed) — re-rolling: {sent[:40]!r}")
        sys.stdout.flush()

    return best[1], attempts_cap, False


# Chunking targets for the splitter below.
HARD_CAP = 240        # never hand the GPT more than this in one pass
MERGE_TARGET = 160    # pack sentences up to here before starting a new chunk
MIN_STANDALONE = 25   # anything shorter is folded into its neighbour


def _split_sentences(text: str):
    """Split into TTS-sized chunks, merging short sentences together.

    Language-agnostic (handles Latin . ! ? and the Devanagari danda ।), because
    XTTS's built-in splitter crashes on Hindi — its char_limits table has no
    'hi' entry.

    Short fragments are the worst case for clarity: a 7-character line measured
    2.68x its expected duration (pure rambling) and a 21-character one 1.61x,
    while 60-115 character lines land at 0.6-0.8x. Merging clauses back into
    full lines gives the GPT enough context to articulate them, and removes the
    choppy 0.18s seam that used to sit between every clause.
    """
    parts = re.split(r'(?<=[।.!?…])\s+', text.strip())
    units = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # Hard-cap very long fragments so the GPT never exceeds its token limit
        while len(p) > HARD_CAP:
            cut = p.rfind(' ', 0, HARD_CAP)
            if cut <= 0:
                cut = HARD_CAP
            units.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            units.append(p)

    merged = []
    for unit in units:
        if merged and len(merged[-1]) + 1 + len(unit) <= MERGE_TARGET:
            merged[-1] = f"{merged[-1]} {unit}"
        else:
            merged.append(unit)

    # A stray short tail ("बस.") can survive the greedy pass when the chunk
    # before it is already full — fold it back in if it still fits.
    i = 1
    while i < len(merged):
        if len(merged[i]) < MIN_STANDALONE and len(merged[i - 1]) + 1 + len(merged[i]) <= HARD_CAP:
            merged[i - 1] = f"{merged[i - 1]} {merged[i]}"
            del merged[i]
        else:
            i += 1

    return merged or [text.strip()]

class XTTSHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default HTTP logs

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ready"}).encode())
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/synthesize":
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            data = json.loads(body)
        except Exception:
            self.send_response(400)
            self.end_headers()
            return

        text = data.get("text", "").strip()
        speaker_wav = data.get("speaker_wav", "")
        language = data.get("language", "en")
        # Optional per-request expressiveness controls (fall back to tuned defaults)
        temperature = float(data.get("temperature", 0.80))
        speed = float(data.get("speed", 1.0))
        repetition_penalty = float(data.get("repetition_penalty", REPETITION_PENALTY))
        # Callers waiting on time-to-first-audio can pass 1 to skip re-rolls.
        max_attempts = data.get("max_attempts")

        if not text or not speaker_wav:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing text or speaker_wav")
            return

        if not os.path.exists(speaker_wav):
            self.send_response(400)
            self.end_headers()
            self.wfile.write(f"Speaker WAV not found: {speaker_wav}".encode())
            return

        try:
            _req_t0 = time.time()
            lang = language.split("-")[0]  # XTTS wants the bare language code
            print(f"[XTTS Server] Synthesizing cloned voice: '{text[:60]}' with speaker: {os.path.basename(speaker_wav)}")
            sys.stdout.flush()

            with TTS_LOCK:
                # Reuse cached speaker latents — the expensive reference analysis
                # runs once per voice, not once per sentence.
                gpt_cond_latent, speaker_embedding = _get_cached_latents(speaker_wav)

                sentences = _split_sentences(text)
                wav_chunks = []
                total_takes = 0
                guarded = 0
                for sent in sentences:
                    wav, takes, accepted = _synthesize_sentence(
                        sent, lang, gpt_cond_latent, speaker_embedding,
                        temperature, speed, repetition_penalty, max_attempts,
                    )
                    wav_chunks.append(wav)
                    total_takes += takes
                    guarded += (takes > 1)

                # Join sentences with a short natural pause
                pause = np.zeros(int(OUTPUT_SR * 0.18), dtype=np.float32)
                joined = wav_chunks[0]
                for chunk in wav_chunks[1:]:
                    joined = np.concatenate([joined, pause, chunk])

                buf = io.BytesIO()
                sf.write(buf, joined, OUTPUT_SR, subtype='PCM_16', format='WAV')
                wav_bytes = buf.getvalue()

            _total = time.time() - _req_t0
            _audio_s = len(joined) / OUTPUT_SR
            print(f"[XTTS Server] ✅ Done — {len(wav_bytes)} bytes, "
                  f"{len(sentences)} sentence(s), {total_takes} take(s)"
                  + (f", {guarded} re-rolled" if guarded else "")
                  + f" | total={_total:.2f}s audio={_audio_s:.2f}s "
                    f"RTF={_total/_audio_s if _audio_s else 0:.2f}")
            sys.stdout.flush()
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(wav_bytes)))
            self.end_headers()
            self.wfile.write(wav_bytes)
        except Exception as e:
            print(f"[XTTS Server] ❌ Error: {e}", file=sys.stderr)
            sys.stdout.flush()
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())


if __name__ == "__main__":
    _warmup()
    # Refuse to share the port — a second binder must fail loudly, not silently
    # double-serve stale code alongside this instance.
    ThreadingHTTPServer.allow_reuse_address = False
    try:
        server = ThreadingHTTPServer(("localhost", PORT), XTTSHandler)
    except OSError as e:
        print(f"[XTTS Server] Port {PORT} already in use ({e}) — exiting.")
        sys.stdout.flush()
        sys.exit(0)
    print(f"[XTTS Server] Running at http://localhost:{PORT}")
    sys.stdout.flush()
    server.serve_forever()
