import os
import sys
import numpy as np
import scipy.io.wavfile as wavfile

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BACKEND_DIR)

from app.services.rvc_pipeline_service import RVCPipelineService
from app.services.voice_engine import VoiceEngineService, VOICES_DIR

base_wav = os.path.join(VOICES_DIR, "norm_voice-fced54ff_clean.wav")
model_pth = os.path.join(BACKEND_DIR, "uploads", "rvc_models", "voice-fced54ff_clean.pth")

print(f"[TEST] Base audio exists: {os.path.exists(base_wav)}")
print(f"[TEST] Model pth exists: {os.path.exists(model_pth)}")

# Generate base Edge-TTS audio first
import asyncio
text = "hi mera nam sudhansu hai aur main ek voice agent hu"
base_bytes = asyncio.run(VoiceEngineService._edge_tts_generate(text, voice="hi-IN-SwaraNeural"))

temp_base = os.path.join(VOICES_DIR, "test_hindi_base.wav")
with open(temp_base, "wb") as f:
    f.write(base_bytes)

print(f"[TEST] Edge-TTS Hindi base audio size: {len(base_bytes)} bytes")

# Convert with RVC
out_bytes = RVCPipelineService.convert_speech(temp_base, model_pth)

if out_bytes:
    print(f"[TEST] RVC Converted Audio bytes: {len(out_bytes)}")
    test_out_wav = os.path.join(VOICES_DIR, "test_rvc_hindi_out.wav")
    with open(test_out_wav, "wb") as f:
        f.write(out_bytes)
    
    sr, data = wavfile.read(test_out_wav)
    max_amp = np.max(np.abs(data))
    mean_amp = np.mean(np.abs(data))
    print(f"[TEST] Audio SR: {sr} | Data Shape: {data.shape} | Data Type: {data.dtype}")
    print(f"[TEST] Max Amplitude: {max_amp} | Mean Amplitude: {mean_amp}")
else:
    print("[TEST] RVC conversion returned None!")
