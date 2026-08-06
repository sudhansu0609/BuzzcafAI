import os
import sys
import json
import urllib.request

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
VOICES_DIR = os.path.join(BACKEND_DIR, "uploads", "voices")

ref_wav = os.path.join(VOICES_DIR, "norm_voice-fced54ff_clean.wav")
ref_text = "My name is Sudhanshu Shekhar Singh and this is a test to voice clone"
gen_text = "hi, mera naam sudhanshu hai aur main ek voice agent hoon. main dekhna chahta hoon ki voice cloning kitni achhi hui hai"

payload = {
    "text": gen_text,
    "speaker_wav": ref_wav,
    "ref_text": ref_text
}

data = json.dumps(payload).encode("utf-8")
req = urllib.request.Request("http://127.0.0.1:8097/synthesize", data=data, headers={"Content-Type": "application/json"})

try:
    with urllib.request.urlopen(req) as resp:
        audio_bytes = resp.read()
        print(f"[TEST CLEAN LATIN F5] Received Audio Bytes: {len(audio_bytes)}")
        out_wav = os.path.join(VOICES_DIR, "clean_latin_f5_out.wav")
        with open(out_wav, "wb") as f:
            f.write(audio_bytes)
        print(f"[TEST CLEAN LATIN F5] Saved clean audio to: {out_wav} (size: {os.path.getsize(out_wav)} bytes)")
except Exception as e:
    print(f"[TEST CLEAN LATIN F5] F5 Error: {e}")
