import os
import sys
import torch
import librosa
import soundfile as sf
import io
import asyncio
import whisper

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND_DIR)

from app.services.voice_engine import VoiceEngineService
from app.services.rvc_pipeline_service import RVCPipelineService

RVC_MODELS_DIR = os.path.join(BACKEND_DIR, "uploads", "rvc_models")
model_pth = os.path.join(RVC_MODELS_DIR, "default_voice.pth")

print(f"[RVC TEST] CUDA Available: {torch.cuda.is_available()} ({torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'})")

async def run_test():
    # 1. Generate clean Hindi base audio with MadhurNeural
    text = "हाय मेरा नाम सुधांशु है और मैं एक वॉइस एजेंट हूं। मैं देखना चाहता हूं कि वॉइस क्लोनिंग कितनी अच्छी हुई है।"
    print("[RVC TEST] Generating clean Hindi base audio using Edge-TTS...")
    base_bytes = await VoiceEngineService._edge_tts_generate(text, pitch=1.0, rate=1.0, voice="hi-IN-MadhurNeural")
    
    base_path = os.path.join(BACKEND_DIR, "uploads", "voices", "test_rvc_base.wav")
    y, sr = librosa.load(io.BytesIO(base_bytes), sr=44100)
    sf.write(base_path, y, 44100, subtype='PCM_16')
    print(f"[RVC TEST] Base audio written to: {base_path} ({os.path.getsize(base_path)} bytes)")

    # 2. Run RVC Conversion
    print(f"[RVC TEST] Converting base audio using RVC Model: {os.path.basename(model_pth)}...")
    rvc_bytes = RVCPipelineService.convert_speech(base_path, model_pth, f0_pitch_shift=0)
    
    if rvc_bytes:
        out_path = os.path.join(BACKEND_DIR, "uploads", "voices", "sudhanshu_rvc_cloned.wav")
        with open(out_path, "wb") as f:
            f.write(rvc_bytes)
        print(f"[RVC TEST] SUCCESS! RVC Cloned audio saved to: {out_path} ({len(rvc_bytes)} bytes)")

        # Whisper verification
        m = whisper.load_model("base")
        res = m.transcribe(out_path)
        print(f"[WHISPER VERIFICATION OF RVC CLONE]:\n{res['text'].encode('utf-8').decode('utf-8')}")
    else:
        print("[RVC TEST] RVC conversion returned None!")

if __name__ == "__main__":
    asyncio.run(run_test())
