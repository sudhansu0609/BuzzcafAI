import os
import sys
import torch

os.environ["COQUI_TOS_AGREED"] = "1"

# 1. PyTorch 2.6 weights_only patch for Coqui model loading
_original_torch_load = torch.load
def _patched_torch_load(*args, **kwargs):
    kwargs["weights_only"] = False
    return _original_torch_load(*args, **kwargs)
torch.load = _patched_torch_load

# 2. Torchaudio soundfile backend patch for robust Windows audio loading
import torchaudio
import soundfile as sf

def _patched_torchaudio_load(filepath, **kwargs):
    data, sr = sf.read(filepath)
    if len(data.shape) == 1:
        tensor = torch.from_numpy(data).float().unsqueeze(0)
    else:
        tensor = torch.from_numpy(data.T).float()
    return tensor, sr

torchaudio.load = _patched_torchaudio_load

try:
    from TTS.api import TTS

    print("Initializing Coqui XTTS v2 model...")
    tts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2", progress_bar=False, gpu=False)

    ref_wav = "uploads/voices/voice-03a26a38_voice1.wav"
    out_wav = "uploads/voices/xtts_test_cloned.wav"

    if os.path.exists(ref_wav):
        print(f"Synthesizing cloned voice for reference speaker: {ref_wav}...")
        tts.tts_to_file(
            text="Hello! This is a test of true zero-shot neural voice cloning powered by Coqui XTTS v2.",
            speaker_wav=ref_wav,
            language="en",
            file_path=out_wav
        )
        print("[SUCCESS] XTTS v2 voice cloning completed successfully!")
    else:
        print(f"Reference WAV file not found at {ref_wav}")
except Exception as e:
    print(f"Error during XTTS test: {e}")
