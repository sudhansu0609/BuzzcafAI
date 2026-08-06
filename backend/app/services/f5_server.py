"""
MidnightBuzz F5-TTS Persistent Microservice
Loads F5-TTS once at startup and stays alive on port 8097.
The main backend calls http://localhost:8097/synthesize for high-quality voice cloning.
"""
import os
import sys
import uuid
import torch
import soundfile as sf
import warnings
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import json

warnings.filterwarnings("ignore")

# Force UTF-8 stdout on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)
if sys.stderr.encoding != 'utf-8':
    sys.stderr = open(sys.stderr.fileno(), mode='w', encoding='utf-8', buffering=1)

# PyTorch 2.6 compatibility patch
_orig_load = torch.load
def _patched_load(*args, **kwargs):
    kwargs["weights_only"] = False
    return _orig_load(*args, **kwargs)
torch.load = _patched_load

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VOICES_DIR = os.path.join(BACKEND_DIR, "uploads", "voices")
PORT = 8098

import importlib.abc
import importlib.machinery
import re

class FairseqPatcher(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "hydra.conf":
            for finder in sys.meta_path:
                if finder is self: continue
                if hasattr(finder, 'find_spec'):
                    spec = finder.find_spec(fullname, path, target)
                    if spec:
                        original_loader = spec.loader
                        class PatchingLoader(importlib.abc.Loader):
                            def create_module(self, spec):
                                return original_loader.create_module(spec) if hasattr(original_loader, 'create_module') else None
                            def exec_module(self, module):
                                source = original_loader.get_source(fullname)
                                if fullname == "hydra.conf":
                                    source = "from dataclasses import field\n" + source
                                    source = re.sub(r'(\w+):\s*([A-Za-z0-9_.]+(?:\[.*?\])?)\s*=\s*([A-Za-z0-9_.]+)\(\)', r'\1: \2 = field(default_factory=\3)', source)
                                code = compile(source, spec.origin, 'exec')
                                exec(code, module.__dict__)
                        spec.loader = PatchingLoader()
                        return spec
        return None

sys.meta_path.insert(0, FairseqPatcher())

print("[F5-TTS Server] Loading F5-TTS model (Flow Matching) — this takes ~30s once...")
sys.stdout.flush()

from f5_tts.api import F5TTS
f5tts = F5TTS()

print(f"[F5-TTS Server] [OK] Model loaded! Listening on port {PORT}")
sys.stdout.flush()

class F5TTSHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

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

        text = data.get("text", "").replace('\n', ' ').replace('\r', ' ').strip()
        speaker_wav = data.get("speaker_wav", "")
        ref_text = data.get("ref_text", "").replace('\n', ' ').replace('\r', ' ').strip()

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

        # Sanitize text and ref_text to prevent non-ASCII UNK tokens (Devanagari/Unicode gibberish)
        clean_gen_text = re.sub(r'[^a-zA-Z0-9\s.,!?-]', '', text)
        clean_gen_text = re.sub(r'\s+', ' ', clean_gen_text).strip()
        if not clean_gen_text:
            clean_gen_text = text

        clean_ref_text = re.sub(r'[^a-zA-Z0-9\s.,!?-]', '', ref_text) if ref_text else ""
        clean_ref_text = re.sub(r'\s+', ' ', clean_ref_text).strip()
        if not clean_ref_text or len(clean_ref_text) < 5:
            clean_ref_text = "My name is Sudhanshu and this is a voice cloning test"

        try:
            out_path = os.path.join(VOICES_DIR, f"f5_out_{uuid.uuid4().hex[:6]}.wav")
            print(f"[F5-TTS Server] Synthesizing clean text: '{clean_gen_text[:60]}' with speaker: {os.path.basename(speaker_wav)}")
            sys.stdout.flush()
            
            # nfe_step=32 gives maximum voice cloning quality and accuracy
            nfe_step = data.get("nfe_step", 32)
            wav, sr, _ = f5tts.infer(
                ref_file=speaker_wav,
                ref_text=clean_ref_text,
                gen_text=clean_gen_text,
                nfe_step=nfe_step
            )
            
            sf.write(out_path, wav, sr)
            with open(out_path, "rb") as f:
                wav_bytes = f.read()
            try:
                os.remove(out_path)
            except:
                pass

            print(f"[F5-TTS Server] [OK] Done — {len(wav_bytes)} bytes")
            sys.stdout.flush()
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(wav_bytes)))
            self.end_headers()
            self.wfile.write(wav_bytes)
        except Exception as e:
            print(f"[F5-TTS Server] [ERROR] {e}", file=sys.stderr)
            sys.stdout.flush()
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())

if __name__ == "__main__":
    server = HTTPServer(("localhost", PORT), F5TTSHandler)
    print(f"[F5-TTS Server] Running at http://localhost:{PORT}")
    sys.stdout.flush()
    server.serve_forever()
