import os
import sys
import argparse
import soundfile as sf
import torch

# PyTorch 2.6 weights_only compatibility patch
_original_torch_load = torch.load
def _patched_torch_load(*args, **kwargs):
    kwargs["weights_only"] = False
    return _original_torch_load(*args, **kwargs)
torch.load = _patched_torch_load

def main():
    parser = argparse.ArgumentParser(description="MidnightBuzz F5-TTS Fast Flow-Matching Zero-Shot Voice Cloning Worker")
    parser.add_argument("--text", required=True, help="Text to speak")
    parser.add_argument("--speaker_wav", required=True, help="Path to reference speaker audio file")
    parser.add_argument("--output_wav", required=True, help="Path to save output wav")

    args = parser.parse_args()

    if not os.path.exists(args.speaker_wav):
        print(f"Error: Speaker WAV file not found at {args.speaker_wav}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading F5-TTS Fast Flow-Matching Model for speaker: {args.speaker_wav}...")
    try:
        from f5_tts.api import F5TTS

        f5tts = F5TTS()
        # nfe_step=16 accelerates Euler ODE flow-matching solver from 55s down to ~2-3s
        wav, sr, _ = f5tts.infer(
            ref_file=args.speaker_wav,
            ref_text="",
            gen_text=args.text,
            nfe_step=16
        )

        sf.write(args.output_wav, wav, sr)
        print(f"[SUCCESS] Generated F5-TTS Fast Flow-Matching Cloned Audio at: {args.output_wav}")
    except Exception as e:
        print(f"Error during F5-TTS zero-shot voice synthesis: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
