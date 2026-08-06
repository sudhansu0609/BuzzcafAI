import os
import sys
import uuid
import json
import torch
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# Ensure PyTorch torch.load patch
_orig_load = torch.load
def _patched_load(*args, **kwargs):
    kwargs["weights_only"] = False
    return _orig_load(*args, **kwargs)
torch.load = _patched_load

try:
    import fairseq.data.dictionary
    torch.serialization.add_safe_globals([fairseq.data.dictionary.Dictionary])
except Exception:
    pass

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND_DIR)

VOICES_DIR = os.path.join(BACKEND_DIR, "uploads", "voices")
RVC_MODELS_DIR = os.path.join(BACKEND_DIR, "uploads", "rvc_models")
os.makedirs(VOICES_DIR, exist_ok=True)
os.makedirs(RVC_MODELS_DIR, exist_ok=True)

PORT = 8099

print(f"[RVC Server] Starting RVC v2 microservice on port {PORT}...")
sys.stdout.flush()

try:
    from app.services.rvc_pipeline_service import RVCPipelineService
    print(f"[RVC Server] ✅ RVC Pipeline Service loaded on GPU ({torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'})")
    sys.stdout.flush()
except Exception as e:
    print(f"[RVC Server] ❌ RVC Pipeline Service load error: {e}")
    sys.stdout.flush()

class RVCServerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

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
        model_path = data.get("model_path", "")
        pitch_shift = int(data.get("pitch_shift", 0))

        if not os.path.exists(model_path):
            model_path = os.path.join(RVC_MODELS_DIR, "default_voice.pth")

        if not os.path.exists(base_audio) or not os.path.exists(model_path):
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Audio or Model file not found")
            return

        try:
            print(f"[RVC Server] Converting base audio {os.path.basename(base_audio)} using RVC model {os.path.basename(model_path)}...")
            sys.stdout.flush()
            
            rvc_bytes = RVCPipelineService.convert_speech(base_audio, model_path, f0_pitch_shift=pitch_shift)

            if rvc_bytes:
                print(f"[RVC Server] ✅ Conversion complete: {len(rvc_bytes)} bytes")
                sys.stdout.flush()
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(rvc_bytes)))
                self.end_headers()
                self.wfile.write(rvc_bytes)
            else:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"RVC conversion returned empty audio")
        except Exception as e:
            print(f"[RVC Server] ❌ Error: {e}", file=sys.stderr)
            sys.stdout.flush()
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())

if __name__ == "__main__":
    server = HTTPServer(("localhost", PORT), RVCServerHandler)
    print(f"[RVC Server] Running at http://localhost:{PORT}")
    sys.stdout.flush()
    server.serve_forever()
