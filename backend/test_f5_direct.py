import os
import sys
import json
import urllib.request

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
VOICES_DIR = os.path.join(BACKEND_DIR, "uploads", "voices")

ref_wav = os.path.join(VOICES_DIR, "norm_voice-fced54ff_clean.wav")
ref_text = "My name is Sudhanshu Shekhar Singh and this is a test to voice clone"
gen_text = "hi mera nam sudhansu hai aur main ek voice agent hu. main dekhna chahta hu ki voice cloning kitni achi hui hai"

payload = {
    "gen_text": gen_text,
    "ref_audio": ref_wav,
    "ref_text": ref_text,
    "nfe_step": 32,
    "speed": 1.0
}

data = json.dumps(payload).encode("utf-8")
req = urllib.request.Request("http://127.0.0.1:8097/synthesize", data=data, headers={"Content-Type": "application/json"})

try:
    with urllib.request.urlopen(req) as resp:
        res_json = json.loads(resp.read().decode("utf-8"))
        out_wav = res_json.get("audio_path")
        print(f"[TEST F5] F5-TTS Generated WAV: {out_wav} (exists: {os.path.exists(out_wav)})")
        if os.path.exists(out_wav):
            size = os.path.getsize(out_wav)
            print(f"[TEST F5] WAV File Size: {size} bytes")
except Exception as e:
    print(f"[TEST F5] F5 Server error: {e}")
