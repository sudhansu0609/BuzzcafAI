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

use_gpu = torch.cuda.is_available()
print(f"[XTTS Server] Loading XTTS v2 model (GPU={use_gpu})...")
sys.stdout.flush()

from TTS.api import TTS
tts_model = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2", progress_bar=False, gpu=use_gpu)

print(f"[XTTS Server] ✅ Model loaded! Listening on port {PORT}")
sys.stdout.flush()

TTS_LOCK = threading.Lock()

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
            out_path = os.path.join(VOICES_DIR, f"xtts_out_{uuid.uuid4().hex[:6]}.wav")
            print(f"[XTTS Server] Synthesizing cloned voice: '{text[:60]}' with speaker: {os.path.basename(speaker_wav)}")
            sys.stdout.flush()
            with TTS_LOCK:
                tts_model.tts_to_file(
                    text=text,
                    speaker_wav=speaker_wav,
                    language=language,
                    file_path=out_path
                )
            with open(out_path, "rb") as f:
                wav_bytes = f.read()
            try:
                os.remove(out_path)
            except Exception:
                pass

            print(f"[XTTS Server] ✅ XTTS Cloned Voice Done — {len(wav_bytes)} bytes")
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
    server = ThreadingHTTPServer(("localhost", PORT), XTTSHandler)
    print(f"[XTTS Server] Running at http://localhost:{PORT}")
    sys.stdout.flush()
    server.serve_forever()
