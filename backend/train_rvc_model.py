import os
import sys
import glob
import torch

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
VOICES_DIR = os.path.join(BACKEND_DIR, "uploads", "voices")
RVC_MODELS_DIR = os.path.join(BACKEND_DIR, "uploads", "rvc_models")
os.makedirs(RVC_MODELS_DIR, exist_ok=True)

from rvc_python.infer import RVCInference

# Initialize RVC on RTX 5060 Ti GPU
rvc = RVCInference(device="cuda:0", models_dir=RVC_MODELS_DIR)

print("[RVC Trainer] System ready for GPU voice model training & voice conversion!")
