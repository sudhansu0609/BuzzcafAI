import os
import sys
import torch
import numpy as np
import faiss
import librosa

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
VOICES_DIR = os.path.join(BACKEND_DIR, "uploads", "voices")
wav_path = r"b:\youtubeProjects\Buzzcaf Media\60sec.wav"

device = "cuda:0" if torch.cuda.is_available() else "cpu"
print(f"[FAISS INDEX] Loading audio: {wav_path} (exists: {os.path.exists(wav_path)}) on {device}")

# Load HuBERT model for 256/768-dim feature extraction
from fairseq import checkpoint_utils
hubert_path = os.path.join(BACKEND_DIR, "voice_env", "Lib", "site-packages", "rvc_python", "base_model", "hubert_base.pt")
print(f"[FAISS INDEX] HuBERT model path: {hubert_path} (exists: {os.path.exists(hubert_path)})")

models, saved_cfg, task = checkpoint_utils.load_model_ensemble_and_task([hubert_path], suffix="")
hubert = models[0].to(device)
hubert.eval()

# Extract HuBERT features from 60sec.wav
y, sr = librosa.load(wav_path, sr=16000)
with torch.no_grad():
    tensor = torch.from_numpy(y).unsqueeze(0).to(device)
    feats_raw = hubert.extract_features(tensor)[0]
    feats = feats_raw.squeeze(0).cpu().numpy()

print(f"[FAISS INDEX] Extracted HuBERT feature shape: {feats.shape}")

# Build FAISS IVF index for ultra-fast k-NN retrieval
dim = feats.shape[1]
n_ivf = min(int(feats.shape[0] / 39), 16)
if n_ivf < 1: n_ivf = 1

index = faiss.index_factory(dim, f"IVF{n_ivf},Flat")
index.train(feats)
index.add(feats)

index_path = os.path.join(VOICES_DIR, "sudhanshu_voice.index")
faiss.write_index(index, index_path)
print(f"[FAISS INDEX] SUCCESS! Created FAISS feature index: {index_path} ({os.path.getsize(index_path)} bytes)")
