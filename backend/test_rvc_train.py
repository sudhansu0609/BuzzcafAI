import os
import sys
import torch

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
VOICES_DIR = os.path.join(BACKEND_DIR, "uploads", "voices")
RVC_MODELS_DIR = os.path.join(BACKEND_DIR, "uploads", "rvc_models")
os.makedirs(RVC_MODELS_DIR, exist_ok=True)

# Select user's uploaded voice sample
sample_wav = os.path.join(VOICES_DIR, "norm_voice-fced54ff_clean.wav")
print(f"[TEST] Target user audio sample: {sample_wav} (exists: {os.path.exists(sample_wav)})")

# Test rvc_python inference
from rvc_python.infer import RVCInference

print("[TEST] Initializing RVCInference on CUDA...")
device = "cuda:0" if torch.cuda.is_available() else "cpu:0"
rvc = RVCInference(device=device)

print(f"[TEST] CUDA Available: {torch.cuda.is_available()} | Device: {device}")
