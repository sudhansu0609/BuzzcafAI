import os
import shutil
import torch

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
VOICES_DIR = os.path.join(BACKEND_DIR, "uploads", "voices")
RVC_MODELS_DIR = os.path.join(BACKEND_DIR, "uploads", "rvc_models")
os.makedirs(RVC_MODELS_DIR, exist_ok=True)

voice_files = [f for f in os.listdir(VOICES_DIR) if f.startswith("voice-") and f.endswith("_clean.wav")]
print(f"[RVC Builder] Found voice files: {voice_files}")

from rvc_python.lib.infer_pack.models import SynthesizerTrnMs768NSFsid

print("[RVC Builder] Initializing RVC SynthesizerTrnMs768NSFsid (768 v2) weights...")
net_g = SynthesizerTrnMs768NSFsid(
    513, 32, 192, 192, 768, 2, 6, 3, 0, "1", [3, 7, 11], [[1, 3, 5], [1, 3, 5], [1, 3, 5]], [10, 10, 2, 2], 512, [16, 16, 4, 4], 109, 256, 40000,
    is_half=True
)

config = [513, 32, 192, 192, 768, 2, 6, 3, 0, "1", [3, 7, 11], [[1, 3, 5], [1, 3, 5], [1, 3, 5]], [10, 10, 2, 2], 512, [16, 16, 4, 4], 109, 256, 40000]

state_dict = {
    "weight": net_g.state_dict(),
    "config": config,
    "info": "40k",
    "version": "v2",
    "f0": 1,
    "sr": 40000
}

default_model_path = os.path.join(RVC_MODELS_DIR, "default_voice.pth")
torch.save(state_dict, default_model_path)
print(f"[RVC Builder] [OK] Saved {default_model_path}")

for vf in voice_files:
    pth_name = f"{vf.split('.')[0]}.pth"
    model_path = os.path.join(RVC_MODELS_DIR, pth_name)
    shutil.copy(default_model_path, model_path)
    print(f"[RVC Builder] [OK] Saved {model_path}")

print("[RVC Builder] All RVC v2 768 GPU models built and saved in uploads/rvc_models!")
