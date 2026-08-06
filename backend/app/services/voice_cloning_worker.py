import os
import sys
import argparse
import torch

# Auto-agree to Coqui CPML non-commercial TOS for automated headless execution
os.environ["COQUI_TOS_AGREED"] = "1"

# 1. PyTorch 2.6 weights_only compatibility patch for Coqui XTTS v2 model loading
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

def main():
    parser = argparse.ArgumentParser(description="MidnightBuzz Zero-Shot Neural Voice Cloning Worker")
    parser.add_argument("--text", required=True, help="Text to speak")
    parser.add_argument("--speaker_wav", required=True, help="Path to reference speaker voice sample")
    parser.add_argument("--output_wav", required=True, help="Path to save output synthesized speech wav")
    parser.add_argument("--language", default="en", help="Language code")

    args = parser.parse_args()

    if not os.path.exists(args.speaker_wav):
        print(f"Error: Speaker WAV file not found at {args.speaker_wav}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading XTTS v2 Zero-Shot Voice Cloning Model for speaker: {args.speaker_wav}...")
    
    try:
        from TTS.api import TTS
        # Initialize Coqui XTTS v2 zero-shot speaker embedding TTS model
        tts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2", progress_bar=False, gpu=False)

        tts.tts_to_file(
            text=args.text,
            speaker_wav=args.speaker_wav,
            language=args.language,
            file_path=args.output_wav
        )
        print(f"[SUCCESS] Generated zero-shot neural cloned voice speech at: {args.output_wav}")
    except Exception as e:
        print(f"Error during XTTS zero-shot voice synthesis: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
