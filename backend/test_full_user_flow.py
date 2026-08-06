import os
import sys
import json
import urllib.request
import urllib.parse

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
wav_path = r"b:\youtubeProjects\Buzzcaf Media\60sec.wav"

# 1. Upload 60sec.wav to clone-voice endpoint
boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
with open(wav_path, "rb") as f:
    wav_data = f.read()

body = (
    f"--{boundary}\r\n"
    f'Content-Disposition: form-data; name="file"; filename="60sec.wav"\r\n'
    f"Content-Type: audio/wav\r\n\r\n"
).encode() + wav_data + f"\r\n--{boundary}--\r\n".encode()

req = urllib.request.Request(
    "http://127.0.0.1:8095/api/agents/clone-voice",
    data=body,
    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    method="POST"
)

try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        res_json = json.loads(resp.read().decode())
        print(f"[FULL FLOW TEST] Upload Response:\n{json.dumps(res_json, indent=2)}")
        sample_path = res_json.get("samplePath")
except Exception as e:
    print(f"[FULL FLOW TEST] Upload Error: {e}")
    sys.exit(1)

# 2. Test TTS Stream with default user text
default_text = "hi mera nam sudhansu hai aur main ek voice agent hu. main dekhna chahta hu ki voice cloning kitni achi hui hai"
tts_url = (
    f"http://127.0.0.1:8095/api/tts/stream?"
    f"text={urllib.parse.quote(default_text)}&"
    f"sample_path={urllib.parse.quote(sample_path)}&"
    f"clone_method=f5"
)

print(f"[FULL FLOW TEST] Requesting TTS Stream: {tts_url}")
tts_req = urllib.request.Request(tts_url)
try:
    with urllib.request.urlopen(tts_req, timeout=60) as resp:
        audio_bytes = resp.read()
        print(f"[FULL FLOW TEST] Received TTS Audio: {len(audio_bytes)} bytes")
        out_file = os.path.join(BACKEND_DIR, "uploads", "voices", "final_full_flow_60sec.wav")
        with open(out_file, "wb") as f:
            f.write(audio_bytes)
        print(f"[FULL FLOW TEST] [SUCCESS] Saved final cloned audio to: {out_file}")
except Exception as e:
    print(f"[FULL FLOW TEST] TTS Error: {e}")
