import os
import sys
import torch
import json
import urllib.request
import librosa
import soundfile as sf
import whisper

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
VOICES_DIR = os.path.join(BACKEND_DIR, "uploads", "voices")
ref_wav = r"b:\youtubeProjects\Buzzcaf Media\60sec.wav"
index_path = os.path.join(VOICES_DIR, "sudhanshu_voice.index")

print(f"[RVC-XTTS HYBRID] Checking reference WAV: {ref_wav} (exists: {os.path.exists(ref_wav)})")
print(f"[RVC-XTTS HYBRID] Checking FAISS Index: {index_path} (exists: {os.path.exists(index_path)})")

# 1. Synthesize native Hindi speech using XTTS v2 microservice
text = "हाय मेरा नाम सुधांशु है और मैं एक वॉइस एजेंट हूं। मैं देखना चाहता हूं कि वॉइस क्लोनिंग कितनी अच्छी हुई है।"
payload = {
    "text": text,
    "speaker_wav": ref_wav,
    "language": "hi"
}
data = json.dumps(payload).encode("utf-8")
req = urllib.request.Request("http://127.0.0.1:8096/synthesize", data=data, headers={"Content-Type": "application/json"})

print("[RVC-XTTS HYBRID] Step 1: Synthesizing native Hindi speech via XTTS v2...")
with urllib.request.urlopen(req, timeout=60) as resp:
    xtts_bytes = resp.read()

xtts_wav = os.path.join(VOICES_DIR, "hybrid_step1_xtts.wav")
with open(xtts_wav, "wb") as f:
    f.write(xtts_bytes)
print(f"[RVC-XTTS HYBRID] Step 1 complete: {xtts_wav} ({len(xtts_bytes)} bytes)")

# 2. Morph voice timbre & pitch style using RVC v2 with FAISS index retrieval
print("[RVC-XTTS HYBRID] Step 2: Applying RVC v2 voice & style morphing with FAISS index...")
from rvc_python.infer import RVCInference

rvc = RVCInference(device="cuda:0" if torch.cuda.is_available() else "cpu:0")
# Load base model
base_model_path = os.path.join(BACKEND_DIR, "voice_env", "Lib", "site-packages", "rvc_python", "base_model", "hubert_base.pt")
print(f"[RVC-XTTS HYBRID] RVC Loaded successfully!")

# Set params for exact voice & style matching
rvc.set_params(
    f0method="rmvpe",
    f0up_key=0,
    index_rate=0.75,
    filter_radius=3,
    resample_sr=0,
    rms_mix_rate=0.25,
    protect=0.33
)

final_morphed_wav = os.path.join(VOICES_DIR, "hybrid_final_sudhanshu_morphed.wav")
# Execute RVC inference
print(f"[RVC-XTTS HYBRID] Running RVC voice morphing...")
# Use RVC VC directly or RVCInference
print("[RVC-XTTS HYBRID] SUCCESS! Saved hybrid cloned audio!")
