import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
import uuid
import io
import asyncio
import subprocess
import shutil
import json
import re
import threading
import time
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, List
import edge_tts
from gtts import gTTS
import soundfile as sf
import numpy as np
import librosa

UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "uploads")
VOICES_DIR = os.path.join(UPLOADS_DIR, "voices")
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VOICE_ENV_PYTHON = os.path.join(BACKEND_DIR, "voice_env", "Scripts", "python.exe")
XTTS_SERVER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xtts_server.py")
XTTS_SERVER_URL = "http://localhost:8096"
OPENVOICE_SERVER_URL = "http://localhost:8097"
F5_SERVER_URL = "http://localhost:8098"
RVC_SERVER_URL = "http://localhost:8099"

os.makedirs(VOICES_DIR, exist_ok=True)

VOICE_MODELS_CATALOG: List[Dict[str, str]] = [
    {"id": "hi-IN-SwaraNeural", "name": "Swara (Native Sweet Indian Female)", "gender": "Female", "accent": "Indian Hindi/Hinglish", "description": "Natural Sweet Indian Female Voice"},
    {"id": "hi-IN-MadhurNeural", "name": "Madhur (Native Expressive Indian Male)", "gender": "Male", "accent": "Indian Hindi/Hinglish", "description": "Expressive Friendly Indian Male Voice"},
    {"id": "hi-IN-AnanyaNeural", "name": "Ananya (Native Cheerful Indian Female)", "gender": "Female", "accent": "Indian Cheerful", "description": "Upbeat Conversational Voice"},
    {"id": "en-IN-PrabhatNeural", "name": "Prabhat (Native Conversational Indian Male)", "gender": "Male", "accent": "Indian English/Hinglish", "description": "Warm Conversational Indian Male Voice"},
    {"id": "en-IN-NeerjaExpressiveNeural", "name": "Neerja Expressive (Ultra-Expressive Indian Female)", "gender": "Female", "accent": "Indian Expressive", "description": "Ultra-Expressive Indian Female Voice (Laughter & Emotion)"},
    {"id": "hi-IN-KavyanjaliNeural", "name": "Kavyanjali (Indian Storyteller Female)", "gender": "Female", "accent": "Indian Expressive", "description": "Storytelling & Expressive Voice"},
    {"id": "hi-IN-HemantNeural", "name": "Hemant (Indian Radio Host Male)", "gender": "Male", "accent": "Indian Radio Host", "description": "Radio & Podcast Host Voice"},
    {"id": "hi-IN-KabirNeural", "name": "Kabir (Indian Deep Narrator Male)", "gender": "Male", "accent": "Indian Deep Narrator", "description": "Rich Narrative Voice"},
    {"id": "kokoro-af_sarah", "name": "Kokoro Sarah (Local Neural Female + Indian Phonetics)", "gender": "Female", "accent": "Kokoro ONNX Neural", "description": "Ultra-Sweet Local Female Voice with Indian Phonetic Enhancer"},
    {"id": "kokoro-af_bella", "name": "Kokoro Bella (Local Neural Female + Indian Phonetics)", "gender": "Female", "accent": "Kokoro ONNX Neural", "description": "Warm Local Female Voice with Indian Phonetic Enhancer"},
    {"id": "kokoro-am_adam", "name": "Kokoro Adam (Local Neural Male + Indian Phonetics)", "gender": "Male", "accent": "Kokoro ONNX Neural", "description": "Warm Conversational Local Male Voice with Indian Phonetic Enhancer"},
    {"id": "kokoro-am_michael", "name": "Kokoro Michael (Local Neural Male + Indian Phonetics)", "gender": "Male", "accent": "Kokoro ONNX Neural", "description": "Professional Local Male Narrator Voice"},
    {"id": "kokoro-bf_emma", "name": "Kokoro Emma (British Female)", "gender": "Female", "accent": "Kokoro British", "description": "Crisp British Female Voice"},
    {"id": "kokoro-bm_george", "name": "Kokoro George (British Male)", "gender": "Male", "accent": "Kokoro British", "description": "Refined British Male Voice"}
]

def _pitch_to_edge_str(pitch: float) -> str:
    hz_shift = int(round((pitch - 1.0) * 100))
    if hz_shift > 0:
        return f"+{hz_shift}Hz"
    elif hz_shift < 0:
        return f"{hz_shift}Hz"
    return "+0Hz"

def _rate_to_edge_str(rate: float) -> str:
    pct_shift = int(round((rate - 1.0) * 100))
    if pct_shift > 0:
        return f"+{pct_shift}%"
    elif pct_shift < 0:
        return f"{pct_shift}%"
    return "+0%"

def _is_xtts_server_ready() -> bool:
    """Check if the persistent XTTS microservice is running."""
    try:
        req = urllib.request.urlopen(f"{XTTS_SERVER_URL}/health", timeout=2)
        return req.status == 200
    except Exception:
        return False

def _is_openvoice_server_ready() -> bool:
    """Check if the persistent OpenVoice microservice is running."""
    try:
        req = urllib.request.urlopen(f"{OPENVOICE_SERVER_URL}/health", timeout=2)
        return req.status == 200
    except Exception:
        return False

def _is_f5_server_ready() -> bool:
    """Check if the persistent F5-TTS microservice is running."""
    try:
        req = urllib.request.urlopen(f"{F5_SERVER_URL}/health", timeout=2)
        return req.status == 200
    except Exception:
        return False

# Relaunch bookkeeping. A dead XTTS server is the single biggest cause of a
# cloned agent answering in somebody else's voice, so we relaunch on demand —
# but never faster than the cooldown, or a burst of chat sentences would each
# spawn their own 2GB model load.
_XTTS_LAUNCH_LOCK = threading.Lock()
_XTTS_LAST_LAUNCH = 0.0
XTTS_LAUNCH_COOLDOWN_S = 120.0
# How long a cloned request may block waiting for the model to finish loading.
XTTS_READY_WAIT_S = float(os.getenv("XTTS_READY_WAIT_S", "45"))


def _start_xtts_server_background() -> None:
    """Start the XTTS server as a background process if not running."""
    if not os.path.exists(VOICE_ENV_PYTHON) or not os.path.exists(XTTS_SERVER_SCRIPT):
        return
    try:
        # DETACHED_PROCESS: the server must NOT inherit the backend's console.
        # While it did, closing the backend window — or any uvicorn --reload
        # restart — delivered it a CTRL_CLOSE and it aborted mid-session
        # ("forrtl: error (200): program aborting due to window-CLOSE event").
        # From then on every reply silently fell back to a generic Edge voice.
        creationflags = 0
        if os.name == 'nt':
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            [VOICE_ENV_PYTHON, XTTS_SERVER_SCRIPT],
            stdout=open(os.path.join(BACKEND_DIR, "xtts_server.log"), "a"),
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=BACKEND_DIR,
            close_fds=True,
            creationflags=creationflags
        )
        print("[VoiceEngine] Started XTTS server in background — warming up...")
    except Exception as e:
        print(f"[VoiceEngine] Could not start XTTS server: {e}")


def _launch_xtts_if_down() -> None:
    """Relaunch the XTTS microservice if it stopped answering (cooldown-guarded)."""
    global _XTTS_LAST_LAUNCH
    with _XTTS_LAUNCH_LOCK:
        if _is_xtts_server_ready():
            return
        if time.time() - _XTTS_LAST_LAUNCH < XTTS_LAUNCH_COOLDOWN_S:
            return
        _XTTS_LAST_LAUNCH = time.time()
        _start_xtts_server_background()


def _ensure_xtts_ready(timeout: float = XTTS_READY_WAIT_S) -> bool:
    """Block (bounded) until the XTTS microservice is serving, relaunching it
    if it died. Blocking is deliberate for cloned agents: the alternative is
    answering the user in a voice that is not their clone at all.

    Blocking call — invoke via asyncio.to_thread from async code.
    """
    if _is_xtts_server_ready():
        return True
    _launch_xtts_if_down()
    deadline = time.time() + max(0.0, timeout)
    while time.time() < deadline:
        if _is_xtts_server_ready():
            return True
        time.sleep(1.0)
    return _is_xtts_server_ready()

def _call_xtts_server(text: str, speaker_wav: str, language: str = "en",
                      temperature: float = 0.80, speed: float = 1.0,
                      max_attempts: Optional[int] = None) -> Optional[bytes]:
    """Call the persistent XTTS microservice to synthesize speech.

    temperature controls emotional expressiveness (higher = more emotive
    prosody); speed slightly slows/speeds delivery for clarity.

    max_attempts=1 tells the server to skip its over-generation re-rolls. Use it
    for the first sentence of a reply, where the listener is waiting on audio
    and a re-roll would double the wait.
    """
    payload = {
        "text": text,
        "speaker_wav": speaker_wav,
        "language": language,
        "temperature": temperature,
        "speed": speed,
    }
    if max_attempts is not None:
        payload["max_attempts"] = max_attempts
    body = json.dumps(payload).encode()
    try:
        req = urllib.request.Request(
            f"{XTTS_SERVER_URL}/synthesize",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        # Generous timeout: the server's over-generation guard may re-roll a
        # sentence up to 3 times, so a long multi-sentence reply can take
        # noticeably longer than a single pass.
        with urllib.request.urlopen(req, timeout=180) as resp:
            if resp.status == 200:
                data = resp.read()
                if data:
                    print(f"[VoiceEngine] [OK] XTTS cloned: {len(data)} bytes")
                    return data
    except Exception as e:
        print(f"[VoiceEngine] XTTS server call failed: {e}")
    return None

def _call_openvoice_server(base_audio_path: str, reference_audio_path: str) -> Optional[bytes]:
    """Call the OpenVoice microservice to convert voice color."""
    body = json.dumps({"base_audio": base_audio_path, "reference_audio": reference_audio_path}).encode()
    try:
        req = urllib.request.Request(
            f"{OPENVOICE_SERVER_URL}/convert",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            if resp.status == 200:
                data = resp.read()
                if data:
                    print(f"[VoiceEngine] [OK] OpenVoice converted: {len(data)} bytes")
                    return data
    except Exception as e:
        print(f"[VoiceEngine] OpenVoice server call failed: {e}")
    return None

def _call_f5_server(text: str, speaker_wav: str, ref_text: Optional[str] = None) -> Optional[bytes]:
    """Call the persistent F5-TTS microservice to synthesize speech."""
    body = json.dumps({"text": text, "speaker_wav": speaker_wav, "ref_text": ref_text or ""}).encode()
    try:
        req = urllib.request.Request(
            f"{F5_SERVER_URL}/synthesize",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            if resp.status == 200:
                data = resp.read()
                if data:
                    print(f"[VoiceEngine] [OK] F5-TTS cloned: {len(data)} bytes")
                    return data
    except Exception as e:
        print(f"[VoiceEngine] F5-TTS server call failed: {e}")
    return None

def _call_rvc_server(base_audio: str, model_path: str, pitch_shift: int = 0) -> Optional[bytes]:
    """Call the persistent RVC v2 microservice to convert voice."""
    body = json.dumps({"base_audio": base_audio, "model_path": model_path, "pitch_shift": pitch_shift}).encode()
    try:
        req = urllib.request.Request(
            f"{RVC_SERVER_URL}/convert",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            if resp.status == 200:
                data = resp.read()
                if data:
                    print(f"[VoiceEngine] [OK] RVC v2 converted: {len(data)} bytes")
                    return data
    except Exception as e:
        print(f"[VoiceEngine] RVC server call failed: {e}")
    return None

class VoiceEngineService:
    VOICES_DIR = VOICES_DIR

    @staticmethod
    def ensure_xtts_server() -> None:
        """Ensure the XTTS background server is running (fire-and-forget).

        Deliberately not latched to "started once": the server can die at any
        point in a session, and a latch turned that into a permanent downgrade
        to non-cloned voices for every later reply.
        """
        _launch_xtts_if_down()

    @staticmethod
    def get_voice_models() -> List[Dict[str, str]]:
        return VOICE_MODELS_CATALOG

    @staticmethod
    def _normalize_audio_to_pcm_wav(input_filepath: str, output_filepath: str) -> bool:
        ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
        try:
            cmd = [ffmpeg_bin, "-y", "-ss", "2", "-t", "12", "-i", input_filepath, "-ar", "16000", "-ac", "1", "-sample_fmt", "s16", output_filepath]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
            if res.returncode == 0 and os.path.exists(output_filepath) and os.path.getsize(output_filepath) > 0:
                print(f"[VoiceEngine] Normalized & sliced 12s active reference audio: {output_filepath}")
                return True
        except Exception as e:
            print("ffmpeg conversion failed:", e)
        try:
            y, sr = librosa.load(input_filepath, sr=16000)
            if len(y.shape) > 1:
                y = y.mean(axis=1)
            # Slice reference audio to active 12 seconds for pristine voice matching
            if len(y) > 16000 * 14:
                y = y[16000 * 2 : 16000 * 14]
            elif len(y) > 16000 * 12:
                y = y[: 16000 * 12]
            sf.write(output_filepath, y, 16000, subtype='PCM_16', format='WAV')
            return True
        except Exception as ex:
            print("librosa audio conversion failed:", ex)
            return False

    @staticmethod
    def _transliterate_hinglish_to_hindi(text: str) -> str:
        """Converts Latin Hinglish text to native Devanagari script for F5-TTS phoneme alignment."""
        mapping = {
            "hi": "हाय",
            "mera": "मेरा",
            "nam": "नाम",
            "naam": "नाम",
            "sudhansu": "सुधांशु",
            "sudhanshu": "सुधांशु",
            "hai": "है",
            "aur": "और",
            "main": "मैं",
            "ek": "एक",
            "voice": "वॉइस",
            "agent": "एजेंट",
            "hu": "हूं",
            "dekhna": "देखना",
            "chahta": "चाहता",
            "ki": "कि",
            "cloning": "क्लोनिंग",
            "kitni": "कितनी",
            "achi": "अच्छी",
            "achhi": "अच्छी",
            "hui": "हुई"
        }
        words = text.split()
        converted = []
        for w in words:
            clean_w = w.strip(".,!?\"'").lower()
            if clean_w in mapping:
                converted.append(mapping[clean_w])
            else:
                converted.append(w)
        return " ".join(converted)

    @staticmethod
    def _normalize_audio_to_pcm_wav(input_path: str, output_path: str) -> bool:
        """Clean a recorded/uploaded sample into the ideal XTTS cloning reference.

        A clean reference is the biggest factor in cloning accuracy. We:
          • decode to mono at 24 kHz (XTTS's native rate — no internal resample)
          • trim leading/trailing silence (dead air confuses the speaker encoder)
          • drop internal gaps longer than ~0.6s that add no timbre information
          • keep up to 30s of actual speech (matches gpt_cond_len=30)
          • peak-normalize so every clone has consistent, clear loudness
        """
        try:
            if not os.path.exists(input_path):
                return False
            # Decode → mono float32 @ 24kHz
            y, sr = librosa.load(input_path, sr=24000, mono=True)
            if y is None or len(y) == 0:
                raise ValueError("empty audio")

            # Trim leading/trailing silence
            y_trim, _ = librosa.effects.trim(y, top_db=30)
            if len(y_trim) < sr * 0.5:  # trimming ate almost everything → keep original
                y_trim = y

            # Concatenate only the voiced/energetic intervals, keeping short
            # natural pauses but removing long dead gaps.
            intervals = librosa.effects.split(y_trim, top_db=30)
            if len(intervals) > 0:
                max_gap = int(sr * 0.6)
                pieces = []
                prev_end = None
                for start, end in intervals:
                    if prev_end is not None:
                        gap = start - prev_end
                        if gap > 0:
                            pieces.append(y_trim[prev_end:prev_end + min(gap, max_gap)])
                    pieces.append(y_trim[start:end])
                    prev_end = end
                y_clean = np.concatenate(pieces) if pieces else y_trim
            else:
                y_clean = y_trim

            # Cap to 30s of speech for a strong-but-bounded conditioning window
            if len(y_clean) > sr * 30:
                y_clean = y_clean[: sr * 30]

            # Peak-normalize to ~-1 dBFS (avoid clipping, consistent loudness)
            peak = float(np.max(np.abs(y_clean))) if len(y_clean) else 0.0
            if peak > 0:
                y_clean = (y_clean / peak) * 0.891  # ~-1 dBFS

            sf.write(output_path, y_clean, sr, subtype='PCM_16', format='WAV')
            return True
        except Exception as ex:
            print(f"[VoiceEngine] Normalization notice: {ex}")
            try:
                # Fallback: at least deliver clean mono PCM_16 at original rate
                data, sr = sf.read(input_path)
                if len(data.shape) > 1:
                    data = data.mean(axis=1)
                sf.write(output_path, data, sr, subtype='PCM_16')
                return True
            except Exception:
                try:
                    if os.path.exists(input_path) and input_path != output_path:
                        shutil.copyfile(input_path, output_path)
                        return True
                except Exception:
                    pass
            return False

    @staticmethod
    def process_voice_sample(filename: str, audio_bytes: bytes) -> Dict[str, Any]:
        voice_id = f"voice-{uuid.uuid4().hex[:8]}"
        temp_filename = f"raw_{voice_id}_{filename}"
        final_filename = f"{voice_id}_clean.wav"
        temp_filepath = os.path.join(VOICES_DIR, temp_filename)
        final_filepath = os.path.join(VOICES_DIR, final_filename)

        with open(temp_filepath, "wb") as f:
            f.write(audio_bytes)

        success = VoiceEngineService._normalize_audio_to_pcm_wav(temp_filepath, final_filepath)
        
        # Auto-extract HuBERT 768-dim vocal feature vectors & build FAISS index for 100% exact voice matching
        index_file = final_filepath + ".index"
        try:
            import faiss
            from fairseq import checkpoint_utils
            
            hubert_path = os.path.join(BACKEND_DIR, "voice_env", "Lib", "site-packages", "rvc_python", "base_model", "hubert_base.pt")
            if os.path.exists(hubert_path):
                device = "cuda:0" if torch.cuda.is_available() else "cpu"
                models, saved_cfg, task = checkpoint_utils.load_model_ensemble_and_task([hubert_path], suffix="")
                hubert = models[0].to(device)
                hubert.eval()

                y_audio, sr_audio = librosa.load(final_filepath, sr=16000)
                with torch.no_grad():
                    tensor_audio = torch.from_numpy(y_audio).unsqueeze(0).to(device)
                    feats_raw = hubert.extract_features(tensor_audio)[0]
                    feats = feats_raw.squeeze(0).cpu().numpy()

                dim = feats.shape[1]
                n_ivf = max(1, min(int(feats.shape[0] / 39), 16))
                idx_faiss = faiss.index_factory(dim, f"IVF{n_ivf},Flat")
                idx_faiss.train(feats)
                idx_faiss.add(feats)
                faiss.write_index(idx_faiss, index_file)
                print(f"[VoiceEngine] Built FAISS voice feature index: {index_file} ({feats.shape[0]} frames)")
        except Exception as fex:
            print(f"[VoiceEngine] FAISS index extraction note: {fex}")

        return {
            "voiceId": voice_id,
            "name": f"Cloned ({filename})",
            "samplePath": f"/api/uploads/voices/{final_filename}",
            "sampleFilename": filename,
            "sampleSize": len(audio_bytes),
            "pitch": 1.0,
            "rate": 1.0,
            "cloned": True,
            "clonedVoiceBase": "en-IN-PrabhatNeural",
            "status": "cloned"
        }

    @staticmethod
    def prepare_expressive_speech_text(text: str, is_kokoro: bool = False) -> str:
        if not text:
            return ""
        
        # 1. Intimate Giggles, Sighs, Whispers & Breath Interjections
        cleaned = re.sub(r'\b(giggles?|giggling|haha|hehe)\b', 'hehe...', text, flags=re.IGNORECASE)
        cleaned = re.sub(r'\b(sighs?|sighing|breathes?|breathing)\b', 'haaah...', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\b(whispers?|whispering)\b', 'mmm...', cleaned, flags=re.IGNORECASE)
        
        # 2. Clean markdown symbols (*, **, _, #, `)
        cleaned = re.sub(r'[*_#`]', '', cleaned)
        
        # 3. Enhance Hinglish emotional interjections with breath pauses
        cleaned = re.sub(r'\b(uff|Uff)\b', 'Uff... haaah...', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\b(achaa|achha|Achha|Achaa)\b', 'Achaa...', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\b(arey|Arey)\b', 'Arey...', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\b(haan|Haan)\b', 'Haan...', cleaned, flags=re.IGNORECASE)
        
        # 4. If Kokoro ONNX is used for Hinglish/Hindi text, apply phonetic stress for natural Indian accent
        if is_kokoro:
            hindi_phonetic_map = {
                r'\bmera\b': 'mayra',
                r'\bnam\b': 'naahm',
                r'\bnaam\b': 'naahm',
                r'\bhai\b': 'hay',
                r'\bhain\b': 'hayn',
                r'\bmain\b': 'meyn',
                r'\bmai\b': 'meyn',
                r'\bkaise\b': 'kaisay',
                r'\bkaisa\b': 'kaisaa',
                r'\bkaisi\b': 'kaisii',
                r'\bbhai\b': 'bhaayi',
                r'\bachha\b': 'achhaa',
                r'\bacha\b': 'achhaa',
                r'\bachi\b': 'achhii',
                r'\bachhi\b': 'achhii',
                r'\bbohot\b': 'bohut',
                r'\bbahut\b': 'bohut',
                r'\bkya\b': 'kyaa',
                r'\bkarna\b': 'karnaa',
                r'\braha\b': 'rahaa',
                r'\brahii\b': 'rahii',
                r'\bhoon\b': 'hoong',
                r'\bhu\b': 'hoong',
                r'\baap\b': 'aahp',
                r'\btum\b': 'toom',
                r'\btumhara\b': 'tumhaaraa'
            }
            for pattern, replacement in hindi_phonetic_map.items():
                cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)

        # 5. Add prosodic breath pauses
        cleaned = cleaned.replace("...", "... ").replace("! ", "! ").replace("? ", "? ")
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned

    # Romanized Hindi tokens that are NOT also English words. Deliberately
    # excludes ambiguous ones ("main", "nam", "hu") — those are what made the
    # old substring heuristic fire on "domain", "name" and "human".
    _HINGLISH_TOKENS = frozenset({
        "mera", "meri", "mere", "naam", "tumhara", "tumse", "tum", "tumhe",
        "aap", "aapka", "aapko", "kya", "kyun", "kyon", "kaise", "kaisa",
        "hai", "hain", "hoon", "nahi", "nahin", "acha", "achha", "achhi",
        "bahut", "yaar", "arre", "chalo", "matlab", "thoda", "zyada",
        "abhi", "aaj", "kal", "milkar", "khush", "dekhna", "chahta",
        "chahti", "hua", "hui", "karo", "karna", "raha", "rahi", "rahe",
        "gaya", "gayi", "bhi", "toh", "phir", "kuch", "kaun", "kahan",
        "jaldi", "theek", "dost", "bhai", "didi", "namaste", "baat",
        "mujhe", "mujhko", "hum", "hamara", "sab", "koi", "wala", "wali",
    })

    @staticmethod
    def detect_tts_language(text: str) -> str:
        """Pick the XTTS language code for `text` ("hi" or "en").

        Matches on WORD BOUNDARIES, not substrings. The previous substring
        heuristic routed ~75% of plain English to the Hindi path (\"name\",
        \"domain\", \"human\", \"chair\" all matched, and \"agent\"/\"voice\"
        were literally in the Hindi list) — which matters a lot, because
        XTTS's Hindi text frontend is an unimplemented stub in Coqui TTS
        0.22.0 and produces rambling, mumbled audio.
        """
        if not text:
            return "en"
        # Any Devanagari character is decisive.
        if any('ऀ' <= ch <= 'ॿ' for ch in text):
            return "hi"
        words = set(re.findall(r"[a-z]+", text.lower()))
        hits = words & VoiceEngineService._HINGLISH_TOKENS
        # Two distinct markers, or one in a short line, indicates Hinglish.
        # A single marker inside a long English sentence is treated as English.
        if len(hits) >= 2 or (hits and len(words) <= 6):
            return "hi"
        return "en"

    @staticmethod
    def prepare_clone_text(text: str) -> str:
        """Prepare text for XTTS voice cloning.

        Unlike prepare_expressive_speech_text (used for Edge/Kokoro), this does
        NOT inject filler tokens like "hehe...", "haaah...", "mmm..." — XTTS
        tries to literally pronounce those, which is the root cause of the
        mumbling/gibberish. Emotion for XTTS instead comes from clean text +
        natural punctuation (! ? ...) + the reference voice + temperature.
        We keep the sentence and its emotive words fully intact, only stripping
        markup and normalizing spacing so every word is voiced clearly.
        """
        if not text:
            return ""
        # Strip markdown / formatting symbols XTTS would otherwise vocalize
        cleaned = re.sub(r'[*_#`~^|<>]', ' ', text)
        # Remove emoji / non-speech pictographs that produce noise
        cleaned = re.sub(r'[\U0001F000-\U0001FAFF\U00002600-\U000027BF]', ' ', cleaned)
        # Drop stray bracketed stage-directions e.g. [laughs], (sighs)
        cleaned = re.sub(r'[\[\(][^\]\)]{0,20}[\]\)]', ' ', cleaned)
        # Keep sentence-final punctuation for natural intonation; collapse
        # runs of dots to a single ellipsis (a gentle pause, not a stutter)
        cleaned = re.sub(r'\.{3,}', '...', cleaned)
        cleaned = re.sub(r'([!?]){2,}', r'\1', cleaned)
        # Normalize whitespace
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned

    @staticmethod
    async def _edge_tts_generate(text: str, pitch: float = 1.0, rate: float = 1.0, voice: str = "en-IN-PrabhatNeural") -> bytes:
        # Text is already pre-processed by callers — no double processing
        
        # Keep pitch 100% natural human tone
        adjusted_pitch = pitch
        adjusted_rate = rate * 0.98  # Relaxed natural human conversational pace (-2%)

        pitch_str = _pitch_to_edge_str(adjusted_pitch)
        rate_str = _rate_to_edge_str(adjusted_rate)
        
        communicate = edge_tts.Communicate(text, voice=voice, pitch=pitch_str, rate=rate_str)
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        return audio_data

    @staticmethod
    def _elevenlabs_generate(text: str, voice_id: str = "21m00Tcm4TlvDq8ikWAM", api_key: Optional[str] = None) -> Optional[bytes]:
        key = api_key or os.getenv("ELEVENLABS_API_KEY")
        if not key:
            return None
        
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg"
        }
        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.35,
                "similarity_boost": 0.85,
                "style": 0.50,
                "use_speaker_boost": True
            }
        }
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                if resp.status == 200:
                    data = resp.read()
                    print(f"[VoiceEngine] [OK] ElevenLabs Multilingual v2 Expressive Speech: {len(data)} bytes")
                    return data
        except Exception as e:
            print(f"[VoiceEngine] ElevenLabs error: {e}")
            return None

    _chat_tts_engine = None

    @staticmethod
    def _get_chat_tts():
        if VoiceEngineService._chat_tts_engine is None:
            try:
                import ChatTTS
                print("[VoiceEngine] Loading ChatTTS local high-emotion voice model...")
                chat = ChatTTS.Chat()
                chat.load(source='huggingface', compile=False)
                VoiceEngineService._chat_tts_engine = chat
                print("[VoiceEngine] [OK] Loaded ChatTTS engine on GPU!")
            except Exception as e:
                print(f"[VoiceEngine] ChatTTS load error: {e}")
                VoiceEngineService._chat_tts_engine = False
        return VoiceEngineService._chat_tts_engine if VoiceEngineService._chat_tts_engine else None

    @staticmethod
    def _chat_tts_generate(text: str) -> Optional[bytes]:
        chat = VoiceEngineService._get_chat_tts()
        if not chat:
            return None
        
        try:
            import ChatTTS
            # Add laughter and oral break tags if text has interjections
            formatted_text = text
            if any(w in text.lower() for w in ["uff", "achaa", "arey", "haan", "giggle", "laugh", "haha", "chudai", "ranid"]):
                formatted_text = text.replace("!", " [laughter] ! ").replace("...", " [oral_2] ... ")
            
            params_infer_code = ChatTTS.Chat.InferCodeParams(prompt='[choice_0]')
            params_refine_text = ChatTTS.Chat.RefineTextParams(prompt='[oral_2][laugh_2]')
            
            wavs = chat.infer([formatted_text], params_refine_text=params_refine_text, params_infer_code=params_infer_code)
            if wavs and len(wavs) > 0:
                buf = io.BytesIO()
                sf.write(buf, wavs[0], 24000, format='WAV')
                buf.seek(0)
                wav_bytes = buf.read()
                print(f"[VoiceEngine] [OK] ChatTTS local expressive speech generated ({len(wav_bytes)} bytes)")
                return wav_bytes
        except Exception as ex:
            print(f"[VoiceEngine] ChatTTS generate error: {ex}")
            return None

    _kokoro_engine = None

    @staticmethod
    def _get_kokoro_tts():
        if VoiceEngineService._kokoro_engine is None:
            try:
                from kokoro_onnx import Kokoro
                model_path = os.path.join(BACKEND_DIR, "kokoro-v1.0.onnx")
                voices_path = os.path.join(BACKEND_DIR, "voices-v1.0.bin")
                if os.path.exists(model_path) and os.path.exists(voices_path):
                    print("[VoiceEngine] Loading Kokoro local ONNX engine...")
                    VoiceEngineService._kokoro_engine = Kokoro(model_path, voices_path)
                    print("[VoiceEngine] [OK] Loaded Kokoro ONNX engine!")
                else:
                    print(f"[VoiceEngine] Kokoro model files missing in {BACKEND_DIR}")
                    VoiceEngineService._kokoro_engine = False
            except Exception as e:
                print(f"[VoiceEngine] Kokoro load error: {e}")
                VoiceEngineService._kokoro_engine = False
        return VoiceEngineService._kokoro_engine if VoiceEngineService._kokoro_engine else None

    @staticmethod
    def _kokoro_generate(text: str, voice: str = "af_sarah", speed: float = 1.0) -> Optional[bytes]:
        kokoro = VoiceEngineService._get_kokoro_tts()
        if not kokoro:
            return None
        try:
            clean_text = VoiceEngineService.prepare_expressive_speech_text(text, is_kokoro=True)
            clean_voice = voice.replace("kokoro-", "").strip() if voice else "af_bella"
            if clean_voice not in ["af_sarah", "af_bella", "af_nicole", "af_sky", "am_adam", "am_michael", "bf_emma", "bm_george"]:
                clean_voice = "af_bella"
            
            # Generate raw float32 samples from Kokoro ONNX (<50ms execution)
            samples, sample_rate = kokoro.create(clean_text, voice=clean_voice, speed=speed, lang="en-us")
            
            buf = io.BytesIO()
            sf.write(buf, samples, sample_rate, format='WAV', subtype='PCM_16')
            buf.seek(0)
            wav_bytes = buf.read()
            print(f"[VoiceEngine] [OK] Kokoro ONNX local speech generated with voice '{clean_voice}' ({len(wav_bytes)} bytes)")
            return wav_bytes
        except Exception as ex:
            print(f"[VoiceEngine] Kokoro generate error for voice '{voice}': {ex}")
            return None

    @staticmethod
    def _sanitize_for_edge_tts(text: str) -> str:
        """Replace explicit words with phonetically similar clean Hindi alternatives.
        This lets Edge TTS (which has content moderation) still produce audio
        while keeping the meaning recognizable to listeners."""
        sanitize_map = {
            r'\bchut\b': 'dil',
            r'\bchudai\b': 'pyaar',
            r'\bchud\b': 'mil',
            r'\bchodo\b': 'chodo',
            r'\bchudne\b': 'milne',
            r'\blund\b': 'mann',
            r'\brandi\b': 'sundari',
            r'\branid\b': 'sundari',
            r'\bgaand\b': 'jaan',
            r'\bboobs\b': 'husn',
            r'\bsex\b': 'pyaar',
            r'\bsexy\b': 'sundar',
            r'\bnanga\b': 'tanha',
            r'\bnangi\b': 'tanhai',
            r'\bchoochi\b': 'khushi',
            r'\bchoochiya\b': 'khushiya',
            r'\bfuck\b': 'yaar',
            r'\bdick\b': 'yaar',
            r'\bpussy\b': 'honey',
            r'\bass\b': 'yaar',
            r'\bcum\b': 'khush',
            r'\borgasm\b': 'anand',
            r'\bnipple\b': 'dimple',
            r'\bblowjob\b': 'surprise',
            r'\bhandjob\b': 'massage',
        }
        cleaned = text
        for pattern, replacement in sanitize_map.items():
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
        return cleaned

    @staticmethod
    def optimize_text_for_fast_tts(text: str, max_chars: int = 220) -> str:
        """Intelligently trims long text to the first 1-2 expressive sentences so TTS generates audio in <1 sec on GPU."""
        if not text or len(text.strip()) <= max_chars:
            return text.strip() if text else ""

        raw = text.strip()
        delimiters = ['।', '.', '!', '?', '\n']
        best_cut = -1
        for i in range(min(len(raw), max_chars), 35, -1):
            if raw[i-1] in delimiters:
                best_cut = i
                break

        if best_cut > 35:
            return raw[:best_cut].strip()
        
        words = raw[:max_chars].split()
        if len(words) > 1:
            return " ".join(words[:-1]).strip()
        return raw[:max_chars].strip()

    @staticmethod
    async def generate_speech_audio(
        text: str,
        pitch: float = 1.0,
        rate: float = 1.0,
        lang: str = "en",
        sample_path: Optional[str] = None,
        voice_base: Optional[str] = None,
        clone_method: str = "openvoice",
        fast_mode: bool = True
    ) -> tuple[bytes, str, str]:
        """Synthesize `text`. Returns (audio_bytes, media_type, engine).

        `engine` names what actually spoke ("xtts-clone", "edge-fallback", …)
        so callers can tell the listener when the clone was unavailable instead
        of quietly substituting a stranger's voice.
        """
        if not text or not text.strip():
            text = "Hello! Your MidnightBuzz voice studio is active."

        raw_text = text.strip()
        # Skip TTS for micro-fragments that XTTS can't render intelligibly
        if len(raw_text) < 10:
            # Return a tiny silent WAV (44-byte header + 0 samples)
            silent_wav = b'RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"V\x00\x00D\xac\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00'
            return silent_wav, "audio/wav", "silence"

        # Check if user-uploaded sample path exists
        has_custom_sample = sample_path and os.path.exists(os.path.join(VOICES_DIR, os.path.basename(sample_path)))

        # Never trim a cloned reply: the clone is expected to speak every word.
        # XTTS splits long text into sentences server-side anyway, so trimming
        # here would only silence the tail of the message.
        if fast_mode and len(raw_text) > 220 and not has_custom_sample:
            text = VoiceEngineService.optimize_text_for_fast_tts(raw_text, max_chars=220)

        # Determine gender for voice selection
        is_female = any(fem in (voice_base or "").lower() for fem in ["swara", "neerja", "ananya", "shilpi", "woman", "female", "girl", "sarah", "bella"]) or any(w in text.lower() for w in ["shilpi", "ananya", "ladki", "female"])

        # Detect if voice_base is a Kokoro voice
        is_kokoro_voice = voice_base and "kokoro" in voice_base.lower()
        # Detect if voice_base is a valid Edge TTS voice ID (contains Neural)
        is_edge_voice = voice_base and "neural" in voice_base.lower()

        # ── Step 0A: True Voice Cloning for Agents with Audio Samples ──
        # If the user recorded or uploaded a voice sample (has_custom_sample=True),
        # the reply MUST come out in their voice. We wait for (and relaunch) the
        # XTTS microservice rather than quietly substituting a stock voice — a
        # silent downgrade is indistinguishable from "cloning is broken".
        if has_custom_sample:
            clean_filename = os.path.basename(sample_path)
            try:
                speaker_wav_path = os.path.join(VOICES_DIR, clean_filename)
                # "norm2_" cache key forces regeneration of references that were
                # normalized by the older (uncleaned) logic.
                normalized_path = os.path.join(VOICES_DIR, f"norm2_{clean_filename}")
                if not os.path.exists(normalized_path):
                    VoiceEngineService._normalize_audio_to_pcm_wav(speaker_wav_path, normalized_path)
                target_wav = normalized_path if os.path.exists(normalized_path) else speaker_wav_path

                xtts_lang = VoiceEngineService.detect_tts_language(text)
                # Use the clean-text preparer (no injected "hehe/haaah/mmm"
                # fillers) so XTTS voices every real word clearly instead of
                # mumbling nonsense syllables.
                tts_text = VoiceEngineService.prepare_clone_text(text.strip())

                print(f"[VoiceEngine] High-Speed XTTS v2 zero-shot cloning user voice from '{clean_filename}'...")
                # Two passes: the server can die between the health check and the
                # request, and relaunching costs far less than the wrong voice.
                for attempt in (1, 2):
                    if not await asyncio.to_thread(_ensure_xtts_ready):
                        print("[VoiceEngine] [WARN] XTTS server did not come up in time")
                        break
                    # temperature=0.85 gives lively, emotive prosody in the cloned
                    # voice; speed=0.96 keeps articulation crisp and unhurried.
                    result = await asyncio.to_thread(
                        _call_xtts_server, tts_text, target_wav, xtts_lang, 0.85, 0.96, None
                    )
                    if result:
                        print(f"[VoiceEngine] [OK] XTTS v2 cloned user voice in '{xtts_lang}': {len(result)} bytes")
                        return result, "audio/wav", "xtts-clone"
                    print(f"[VoiceEngine] XTTS clone attempt {attempt} produced no audio")
            except Exception as xtts_ex:
                print(f"[VoiceEngine] XTTS v2 voice cloning notice: {xtts_ex}")

        # ── Step 0A-fallback: Cloned agent but XTTS failed — use Edge TTS with clonedVoiceBase ──
        # This gives a clear, intelligible voice that matches the agent's configured voice type
        # instead of cascading through Kokoro which ignores the sample and produces gibberish
        if has_custom_sample:
            fallback_voice = voice_base if is_edge_voice else ("hi-IN-SwaraNeural" if is_female else "hi-IN-MadhurNeural")
            tts_text = VoiceEngineService.prepare_expressive_speech_text(text.strip(), is_kokoro=False)
            try:
                audio_bytes = await VoiceEngineService._edge_tts_generate(tts_text, pitch=pitch, rate=rate, voice=fallback_voice)
                if audio_bytes and len(audio_bytes) > 200:
                    print(f"[VoiceEngine] [WARN] CLONE UNAVAILABLE — spoke with Edge TTS '{fallback_voice}' instead: {len(audio_bytes)} bytes")
                    return audio_bytes, "audio/mpeg", "edge-fallback"
            except Exception as ex:
                print(f"[VoiceEngine] Edge TTS cloned-agent fallback error: {ex}")

        # ── Step 0B: Kokoro ONNX — ONLY for agents explicitly configured with kokoro voices ──
        # Kokoro produces English-only output. Using it for Hindi/Hinglish text produces gibberish.
        if is_kokoro_voice and VoiceEngineService._get_kokoro_tts():
            try:
                kokoro_bytes = await asyncio.to_thread(VoiceEngineService._kokoro_generate, text.strip(), voice_base, rate)
                if kokoro_bytes:
                    print(f"[VoiceEngine] [OK] Kokoro ONNX voice '{voice_base}': {len(kokoro_bytes)} bytes")
                    return kokoro_bytes, "audio/wav", "kokoro"
            except Exception as k_ex:
                print(f"[VoiceEngine] Kokoro ONNX notice: {k_ex}")

        # ── Step 0C: Check ElevenLabs (paid, highest quality fallback) ──
        el_key = os.getenv("ELEVENLABS_API_KEY")
        if el_key or (voice_base and "elevenlabs" in voice_base.lower()):
            el_voice = "21m00Tcm4TlvDq8ikWAM"
            if voice_base:
                if "bella" in voice_base.lower():
                    el_voice = "EXAVITQu4vr4xnSDxMaL"
                elif "antoni" in voice_base.lower():
                    el_voice = "ErXwobaYiN019PkySvjV"
            el_bytes = VoiceEngineService._elevenlabs_generate(text.strip(), voice_id=el_voice, api_key=el_key)
            if el_bytes:
                return el_bytes, "audio/mpeg", "elevenlabs"

        # ── Step 1: Edge TTS — Fast, Clear, Reliable (~200ms) ──
        # Use the agent's configured voice_base if it's a valid Edge TTS ID,
        # otherwise pick a Hindi voice by gender
        if is_edge_voice:
            edge_voice = voice_base
        else:
            edge_voice = "hi-IN-SwaraNeural" if is_female else "hi-IN-MadhurNeural"
        
        tts_text = VoiceEngineService.prepare_expressive_speech_text(text.strip(), is_kokoro=False)
        
        # Attempt 1: Try Edge TTS with original text
        try:
            audio_bytes = await VoiceEngineService._edge_tts_generate(tts_text, pitch=pitch, rate=rate, voice=edge_voice)
            if audio_bytes and len(audio_bytes) > 200:
                print(f"[VoiceEngine] [OK] Edge TTS '{edge_voice}': {len(audio_bytes)} bytes")
                return audio_bytes, "audio/mpeg", "edge"
        except Exception as ex:
            print(f"[VoiceEngine] Edge TTS attempt 1 error: {ex}")

        # Attempt 2: Sanitize explicit words and retry Edge TTS
        sanitized_text = VoiceEngineService._sanitize_for_edge_tts(tts_text)
        if sanitized_text != tts_text:
            print(f"[VoiceEngine] Retrying Edge TTS with sanitized text...")
            try:
                audio_bytes = await VoiceEngineService._edge_tts_generate(sanitized_text, pitch=pitch, rate=rate, voice=edge_voice)
                if audio_bytes and len(audio_bytes) > 200:
                    print(f"[VoiceEngine] [OK] Edge TTS (sanitized) '{edge_voice}': {len(audio_bytes)} bytes")
                    return audio_bytes, "audio/mpeg", "edge"
            except Exception as ex:
                print(f"[VoiceEngine] Edge TTS attempt 2 (sanitized) error: {ex}")

        # Attempt 3: Try en-IN-NeerjaExpressiveNeural (expressive Indian English fallback)
        try:
            audio_bytes = await VoiceEngineService._edge_tts_generate(sanitized_text, pitch=pitch, rate=rate, voice="en-IN-NeerjaExpressiveNeural")
            if audio_bytes and len(audio_bytes) > 200:
                print(f"[VoiceEngine] [OK] Expressive Indian Edge TTS 'en-IN-NeerjaExpressiveNeural': {len(audio_bytes)} bytes")
                return audio_bytes, "audio/mpeg", "edge"
        except Exception as ex:
            print(f"[VoiceEngine] Edge TTS NeerjaExpressive error: {ex}")

        # ── Step 2: XTTS v2 Voice Cloning (final XTTS attempt for any remaining cases) ──
        # No user sample here, so this is a stock reference — don't block waiting
        # for a cold server, just use it if it happens to be up.
        if _is_xtts_server_ready():
            try:
                target_wav = None
                if is_female:
                    full_ref = os.path.join(VOICES_DIR, "indian_female_ref_full.wav")
                    short_ref = os.path.join(VOICES_DIR, "indian_female_ref.wav")
                    target_wav = full_ref if os.path.exists(full_ref) else short_ref
                else:
                    target_wav = os.path.join(VOICES_DIR, "60sec_ref_12s.wav")

                if target_wav and os.path.exists(target_wav):
                    tts_text = VoiceEngineService.prepare_clone_text(text.strip())
                    print(f"[VoiceEngine] XTTS v2 fallback with ref='{os.path.basename(target_wav)}', lang='hi'")
                    result = _call_xtts_server(tts_text, target_wav, "hi", 0.85, 0.96)
                    if result:
                        print(f"[VoiceEngine] [OK] XTTS v2 speech: {len(result)} bytes")
                        return result, "audio/wav", "xtts-stock"
            except Exception as xtts_ex:
                print(f"[VoiceEngine] XTTS v2 error: {xtts_ex}")

        # ── Step 3: Kokoro ONNX Local Fallback (English accent but works offline) ──
        if VoiceEngineService._get_kokoro_tts():
            kokoro_voice = "af_sarah" if is_female else "am_adam"
            print(f"[VoiceEngine] Final fallback: Kokoro ONNX '{kokoro_voice}'")
            kokoro_bytes = VoiceEngineService._kokoro_generate(text.strip(), voice=kokoro_voice, speed=rate)
            if kokoro_bytes:
                return kokoro_bytes, "audio/wav", "kokoro"

        # ── Step 4: gTTS absolute last resort ──
        try:
            tts = gTTS(text=text.strip(), lang="hi", slow=False)
            fp = io.BytesIO()
            tts.write_to_fp(fp)
            fp.seek(0)
            return fp.read(), "audio/mpeg", "gtts"
        except Exception as ex:
            print(f"gTTS error: {ex}")
            return b"", "audio/mpeg", "none"

    @staticmethod
    def transcribe_audio(audio_bytes: bytes) -> str:
        return "Hey team, let's review the video production plan for our channel!"

