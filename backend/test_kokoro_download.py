import os
import urllib.request
from kokoro_onnx import Kokoro
import soundfile as sf

MODEL_PATH = "kokoro-v1.0.onnx"
VOICES_PATH = "voices-v1.0.bin"

if not os.path.exists(MODEL_PATH):
    print("Downloading Kokoro v1.0 ONNX model (88MB)...")
    url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
    urllib.request.urlretrieve(url, MODEL_PATH)

if not os.path.exists(VOICES_PATH):
    print("Downloading Kokoro v1.0 voices (300KB)...")
    url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
    urllib.request.urlretrieve(url, VOICES_PATH)

print("=== KOKORO LOCAL MODEL DOWNLOAD COMPLETE ===")
kokoro = Kokoro(MODEL_PATH, VOICES_PATH)

# Synthesize ultra-sweet female voice (af_sarah / af_bella)
samples, sample_rate = kokoro.create(
    "Hello! I am Shilpi, your personal assistant. It is so good to speak with you today!",
    voice="af_sarah",
    speed=1.0,
    lang="en-us"
)

sf.write("temp_kokoro_shilpi.wav", samples, sample_rate)
print("=== KOKORO SHILPI AUDIO GENERATED ===", len(samples))
