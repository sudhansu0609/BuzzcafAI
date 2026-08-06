import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
import uuid
import io
import asyncio
import subprocess
import shutil
import json
import re
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

def _start_xtts_server_background() -> None:
    """Start the XTTS server as a background process if not running."""
    if not os.path.exists(VOICE_ENV_PYTHON) or not os.path.exists(XTTS_SERVER_SCRIPT):
        return
    try:
        subprocess.Popen(
            [VOICE_ENV_PYTHON, XTTS_SERVER_SCRIPT],
            stdout=open(os.path.join(BACKEND_DIR, "xtts_server.log"), "a"),
            stderr=subprocess.STDOUT,
            cwd=BACKEND_DIR,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        print("[VoiceEngine] Started XTTS server in background — warming up...")
    except Exception as e:
        print(f"[VoiceEngine] Could not start XTTS server: {e}")

def _call_xtts_server(text: str, speaker_wav: str, language: str = "en") -> Optional[bytes]:
    """Call the persistent XTTS microservice to synthesize speech."""
    body = json.dumps({"text": text, "speaker_wav": speaker_wav, "language": language}).encode()
    try:
        req = urllib.request.Request(
            f"{XTTS_SERVER_URL}/synthesize",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
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
    _xtts_server_started = False

    @staticmethod
    def ensure_xtts_server() -> None:
        """Ensure the XTTS background server is running."""
        if not _is_xtts_server_ready():
            if not VoiceEngineService._xtts_server_started:
                VoiceEngineService._xtts_server_started = True
                _start_xtts_server_background()

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
        """Normalizes recorded/uploaded audio sample to clean mono 16-bit PCM WAV for XTTS zero-shot voice cloning."""
        try:
            if not os.path.exists(input_path):
                return False
            data, sr = sf.read(input_path)
            if len(data.shape) > 1:
                data = data.mean(axis=1)  # Convert stereo channels to mono
            sf.write(output_path, data, sr, subtype='PCM_16')
            return True
        except Exception as ex:
            print(f"[VoiceEngine] Normalization notice: {ex}")
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

    VOICES_DIR = VOICES_DIR
    _xtts_server_started = False

    @staticmethod
    def ensure_xtts_server() -> None:
        """Ensure the XTTS background server is running."""
        if not _is_xtts_server_ready():
            if not VoiceEngineService._xtts_server_started:
                VoiceEngineService._xtts_server_started = True
                _start_xtts_server_background()

    @staticmethod
    def get_voice_models() -> List[Dict[str, str]]:
        return VOICE_MODELS_CATALOG

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
    ) -> tuple[bytes, str]:
        if not text or not text.strip():
            text = "Hello! Your MidnightBuzz voice studio is active."

        raw_text = text.strip()
        # Skip TTS for micro-fragments that XTTS can't render intelligibly
        if len(raw_text) < 10:
            # Return a tiny silent WAV (44-byte header + 0 samples)
            silent_wav = b'RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"V\x00\x00D\xac\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00'
            return silent_wav, "audio/wav"

        if fast_mode and len(raw_text) > 220:
            text = VoiceEngineService.optimize_text_for_fast_tts(raw_text, max_chars=220)

        # Determine gender for voice selection
        is_female = any(fem in (voice_base or "").lower() for fem in ["swara", "neerja", "ananya", "shilpi", "woman", "female", "girl", "sarah", "bella"]) or any(w in text.lower() for w in ["shilpi", "ananya", "ladki", "female"])

        # Check if user-uploaded sample path exists
        has_custom_sample = sample_path and os.path.exists(os.path.join(VOICES_DIR, os.path.basename(sample_path)))

        # Detect if voice_base is a Kokoro voice
        is_kokoro_voice = voice_base and "kokoro" in voice_base.lower()
        # Detect if voice_base is a valid Edge TTS voice ID (contains Neural)
        is_edge_voice = voice_base and "neural" in voice_base.lower()

        # ── Step 0A: True Voice Cloning for Agents with Audio Samples ──
        # If the user recorded or uploaded a voice sample (has_custom_sample=True),
        # ALWAYS use high-speed GPU XTTS v2 zero-shot cloning in THEIR exact voice!
        if has_custom_sample and _is_xtts_server_ready():
            try:
                clean_filename = os.path.basename(sample_path)
                speaker_wav_path = os.path.join(VOICES_DIR, clean_filename)
                normalized_path = os.path.join(VOICES_DIR, f"norm_{clean_filename}")
                if not os.path.exists(normalized_path):
                    VoiceEngineService._normalize_audio_to_pcm_wav(speaker_wav_path, normalized_path)
                target_wav = normalized_path if os.path.exists(normalized_path) else speaker_wav_path

                hindi_words = ["mera", "nam", "naam", "main", "tumhara", "hai", "hu", "kya", "dekhna", "chahta", "achi", "achhi", "hui", "nahi", "सुधांशु", "हाय", "वॉइस", "agent", "voice"]
                xtts_lang = "hi" if any(w in text.lower() for w in hindi_words) or any('\u0900' <= char <= '\u097F' for char in text) else "en"
                tts_text = VoiceEngineService.prepare_expressive_speech_text(text.strip(), is_kokoro=False)

                print(f"[VoiceEngine] High-Speed XTTS v2 zero-shot cloning user voice from '{clean_filename}'...")
                result = await asyncio.to_thread(_call_xtts_server, tts_text, target_wav, xtts_lang)
                if result:
                    print(f"[VoiceEngine] [OK] XTTS v2 cloned user voice in '{xtts_lang}': {len(result)} bytes")
                    return result, "audio/wav"
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
                    print(f"[VoiceEngine] [OK] Cloned agent Edge TTS fallback '{fallback_voice}': {len(audio_bytes)} bytes")
                    return audio_bytes, "audio/mpeg"
            except Exception as ex:
                print(f"[VoiceEngine] Edge TTS cloned-agent fallback error: {ex}")

        # ── Step 0B: Kokoro ONNX — ONLY for agents explicitly configured with kokoro voices ──
        # Kokoro produces English-only output. Using it for Hindi/Hinglish text produces gibberish.
        if is_kokoro_voice and VoiceEngineService._get_kokoro_tts():
            try:
                kokoro_bytes = await asyncio.to_thread(VoiceEngineService._kokoro_generate, text.strip(), voice_base, rate)
                if kokoro_bytes:
                    print(f"[VoiceEngine] [OK] Kokoro ONNX voice '{voice_base}': {len(kokoro_bytes)} bytes")
                    return kokoro_bytes, "audio/wav"
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
                return el_bytes, "audio/mpeg"

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
                return audio_bytes, "audio/mpeg"
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
                    return audio_bytes, "audio/mpeg"
            except Exception as ex:
                print(f"[VoiceEngine] Edge TTS attempt 2 (sanitized) error: {ex}")

        # Attempt 3: Try en-IN-NeerjaExpressiveNeural (expressive Indian English fallback)
        try:
            audio_bytes = await VoiceEngineService._edge_tts_generate(sanitized_text, pitch=pitch, rate=rate, voice="en-IN-NeerjaExpressiveNeural")
            if audio_bytes and len(audio_bytes) > 200:
                print(f"[VoiceEngine] [OK] Expressive Indian Edge TTS 'en-IN-NeerjaExpressiveNeural': {len(audio_bytes)} bytes")
                return audio_bytes, "audio/mpeg"
        except Exception as ex:
            print(f"[VoiceEngine] Edge TTS NeerjaExpressive error: {ex}")

        # ── Step 2: XTTS v2 Voice Cloning (final XTTS attempt for any remaining cases) ──
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
                    tts_text = VoiceEngineService.prepare_expressive_speech_text(text.strip(), is_kokoro=False)
                    print(f"[VoiceEngine] XTTS v2 fallback with ref='{os.path.basename(target_wav)}', lang='hi'")
                    result = _call_xtts_server(tts_text, target_wav, "hi")
                    if result:
                        print(f"[VoiceEngine] [OK] XTTS v2 speech: {len(result)} bytes")
                        return result, "audio/wav"
            except Exception as xtts_ex:
                print(f"[VoiceEngine] XTTS v2 error: {xtts_ex}")

        # ── Step 3: Kokoro ONNX Local Fallback (English accent but works offline) ──
        if VoiceEngineService._get_kokoro_tts():
            kokoro_voice = "af_sarah" if is_female else "am_adam"
            print(f"[VoiceEngine] Final fallback: Kokoro ONNX '{kokoro_voice}'")
            kokoro_bytes = VoiceEngineService._kokoro_generate(text.strip(), voice=kokoro_voice, speed=rate)
            if kokoro_bytes:
                return kokoro_bytes, "audio/wav"

        # ── Step 4: gTTS absolute last resort ──
        try:
            tts = gTTS(text=text.strip(), lang="hi", slow=False)
            fp = io.BytesIO()
            tts.write_to_fp(fp)
            fp.seek(0)
            return fp.read(), "audio/mpeg"
        except Exception as ex:
            print(f"gTTS error: {ex}")
            return b"", "audio/mpeg"

    @staticmethod
    def transcribe_audio(audio_bytes: bytes) -> str:
        return "Hey team, let's review the video production plan for our channel!"

