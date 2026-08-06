import os
import sys

ref_wav = "uploads/voices/converted.wav"
out_wav = "uploads/voices/f5_test_cloned.wav"

try:
    from f5_tts.api import F5TTS

    print("Initializing F5-TTS Flow-Matching Zero-Shot Voice Cloning Model...")
    f5tts = F5TTS()

    gen_text = "Hello! This is a test of F5-TTS Flow-Matching zero-shot neural voice cloning."

    print(f"Synthesizing cloned voice using F5-TTS for reference speaker: {ref_wav}...")
    f5tts.infer(
        ref_file=ref_wav,
        ref_text="",
        gen_text=gen_text,
        file_wave_container=out_wav
    )
    print(f"[SUCCESS] F5-TTS voice cloning completed! Output saved to: {out_wav}")
except Exception as e:
    print(f"Error during F5-TTS inference: {e}")
