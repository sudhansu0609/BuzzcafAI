import os
import sys
import torch

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
VOICES_DIR = os.path.join(BACKEND_DIR, "uploads", "voices")
RVC_MODELS_DIR = os.path.join(BACKEND_DIR, "uploads", "rvc_models")
os.makedirs(RVC_MODELS_DIR, exist_ok=True)

wav_path = r"b:\youtubeProjects\Buzzcaf Media\60sec.wav"
pth_out = os.path.join(RVC_MODELS_DIR, "sudhanshu_trained.pth")

print(f"[RVC TRAIN] Checking source WAV: {wav_path} (exists: {os.path.exists(wav_path)})")
print(f"[RVC TRAIN] CUDA Available: {torch.cuda.is_available()} ({torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'})")

try:
    from rvc_python.modules.train.preprocess import preprocess_dataset
    print("[RVC TRAIN] Preprocessing dataset...")
    # Preprocess dataset
except Exception as e:
    print(f"[RVC TRAIN] Preprocess module note: {e}")
