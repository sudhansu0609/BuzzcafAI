import urllib.request
import json
import os

F5_SERVER_URL = "http://localhost:8097"
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
VOICES_DIR = os.path.join(BACKEND_DIR, "uploads", "voices")

speaker_wav = os.path.join(VOICES_DIR, "norm_voice-fced54ff_clean.wav")
ref_text = "My name is Sudhanshu Shekhar Singh and this is a test to voice clone. I want to see how much my voice clone is good so that I can get an agent from it."
gen_text = "My name is Sudhanshu Shekhar Singh and this is a test to voice clone. I want to see how much my voice clone is good so that I can get an agent from it."

body = json.dumps({
    "text": gen_text,
    "speaker_wav": speaker_wav,
    "ref_text": ref_text
}).encode()

req = urllib.request.Request(
    f"{F5_SERVER_URL}/synthesize",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST"
)

out_file = os.path.join(VOICES_DIR, "sudhanshu_identical_comparison.wav")
with urllib.request.urlopen(req, timeout=120) as resp:
    if resp.status == 200:
        data = resp.read()
        with open(out_file, "wb") as f:
            f.write(data)
        print(f"[SUCCESS] Identical sentence audio written to {out_file} ({len(data)} bytes)")
    else:
        print("[ERROR]", resp.status)
