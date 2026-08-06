import os
import sys
import json
import urllib.request
import whisper

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
ref_wav = r"b:\youtubeProjects\Buzzcaf Media\60sec.wav"
clean_ref = os.path.join(BACKEND_DIR, "uploads", "voices", "60sec_ref_12s.wav")
target_ref = clean_ref if os.path.exists(clean_ref) else ref_wav

print(f"[XTTS TEST] Testing Coqui XTTS v2 GPU Microservice on port 8096...")
print(f"[XTTS TEST] Reference Audio: {target_ref} ({os.path.getsize(target_ref)} bytes)")

# Hinglish / Hindi text
text = "hi mera nam sudhansu hai aur main ek voice agent hu. main dekhna chahta hu ki voice cloning kitni achi hui hai"

body = json.dumps({
    "text": text,
    "speaker_wav": target_ref,
    "language": "hi"
}).encode()

req = urllib.request.Request(
    "http://localhost:8096/synthesize",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST"
)

out_wav = os.path.join(BACKEND_DIR, "uploads", "voices", "xtts_sudhanshu_real_clone.wav")
try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        if resp.status == 200:
            data = resp.read()
            with open(out_wav, "wb") as f:
                f.write(data)
            print(f"[XTTS TEST] SUCCESS! Saved XTTS cloned voice to: {out_wav} ({len(data)} bytes)")

            # Whisper verification of output
            m = whisper.load_model("base")
            res = m.transcribe(out_wav)
            print(f"[WHISPER VERIFICATION OF XTTS REAL VOICE CLONE]:\n{res['text'].encode('utf-8').decode('utf-8')}")
        else:
            print(f"[XTTS TEST] HTTP Error: {resp.status}")
except Exception as e:
    print(f"[XTTS TEST] Error: {e}")
