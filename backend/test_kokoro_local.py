import os

print("=== TESTING KOKORO-TTS EMOTION VOICE ENGINE ===")
try:
    from kokoro_onnx import Kokoro
    print("[Kokoro] kokoro_onnx imported successfully!")
except ImportError:
    print("[Kokoro] kokoro_onnx not installed. Installing via pip...")
    import subprocess
    subprocess.check_call([os.sys.executable, "-m", "pip", "install", "kokoro-onnx", "soundfile"])
    from kokoro_onnx import Kokoro

print("Kokoro import test passed.")
