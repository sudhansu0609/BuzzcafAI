import sys

modules = ["f5_tts", "ChatTTS", "kokoro", "torch", "torchaudio", "TTS", "rvc_python"]
print("=== CHECKING INSTALLED LOCAL VOICE ENGINES ===")
for m in modules:
    try:
        __import__(m)
        print(f"[INSTALLED] {m}")
    except ImportError:
        print(f"[NOT INSTALLED] {m}")
