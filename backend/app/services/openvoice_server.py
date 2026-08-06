"""
MidnightBuzz OpenVoice V2 Tone Color Converter Microservice
Listens on port 8097
"""
import os
import sys
import uuid
import json
import torch
import warnings
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# Force UTF-8 stdout
if sys.stdout.encoding != 'utf-8':
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)
if sys.stderr.encoding != 'utf-8':
    sys.stderr = open(sys.stderr.fileno(), mode='w', encoding='utf-8', buffering=1)

warnings.filterwarnings("ignore")

PORT = 8097
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OPENVOICE_DIR = os.path.join(BACKEND_DIR, "uploads", "OpenVoice")
CKPT_DIR = os.path.join(OPENVOICE_DIR, "checkpoints_v2", "converter")
VOICES_DIR = os.path.join(BACKEND_DIR, "uploads", "voices")

sys.path.append(OPENVOICE_DIR)

print("[OpenVoice Server] Loading ToneColorConverter...")
sys.stdout.flush()

from openvoice import se_extractor
from openvoice.api import ToneColorConverter

device = "cuda:0" if torch.cuda.is_available() else "cpu"
tone_color_converter = ToneColorConverter(f'{CKPT_DIR}/config.json', device=device)
tone_color_converter.load_ckpt(f'{CKPT_DIR}/checkpoint.pth')

print(f"[OpenVoice Server] ✅ Model loaded on {device}! Listening on port {PORT}")
sys.stdout.flush()

class OpenVoiceHandler(BaseHTTPRequestHandler):
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
        if parsed.path != "/convert":
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

        base_audio = data.get("base_audio", "")
        reference_audio = data.get("reference_audio", "")

        if not os.path.exists(base_audio) or not os.path.exists(reference_audio):
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Base or reference audio missing")
            return

        try:
            out_path = os.path.join(VOICES_DIR, f"ov_out_{uuid.uuid4().hex[:6]}.wav")
            print(f"[OpenVoice Server] Converting... Base: {os.path.basename(base_audio)} | Ref: {os.path.basename(reference_audio)}")
            sys.stdout.flush()

            source_se, _ = se_extractor.get_se(base_audio, tone_color_converter, vad=False)
            target_se, _ = se_extractor.get_se(reference_audio, tone_color_converter, vad=False)

            tone_color_converter.convert(
                audio_src_path=base_audio, 
                src_se=source_se, 
                tgt_se=target_se, 
                output_path=out_path,
                tau=1.0,
                message="@MyShell"
            )

            with open(out_path, "rb") as f:
                wav_bytes = f.read()

            try:
                os.remove(out_path)
            except:
                pass

            print(f"[OpenVoice Server] ✅ Done — {len(wav_bytes)} bytes")
            sys.stdout.flush()
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(wav_bytes)))
            self.end_headers()
            self.wfile.write(wav_bytes)
        except Exception as e:
            print(f"[OpenVoice Server] ❌ Error: {e}", file=sys.stderr)
            sys.stdout.flush()
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())

if __name__ == "__main__":
    server = HTTPServer(("localhost", PORT), OpenVoiceHandler)
    server.serve_forever()
