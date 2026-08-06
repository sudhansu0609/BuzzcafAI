import asyncio
import os
from app.services.voice_engine import VoiceEngineService
from app.services.rvc_pipeline_service import RVCPipelineService

async def main():
    text = "Uff! Achaa, suno... Aaj ka din toh bahut mast hone wala hai! Tum batao, kya plan hai?"
    print("Testing RVC Voice Conversion for true human emotion...")
    
    # 1. Generate base speech
    base_bytes = await VoiceEngineService._edge_tts_generate(text, voice="hi-IN-SwaraNeural")
    temp_base = "temp_rvc_test_base.wav"
    
    import soundfile as sf
    import librosa
    import io
    y, sr = librosa.load(io.BytesIO(base_bytes), sr=24000)
    sf.write(temp_base, y, 24000, subtype='PCM_16')
    print("Base audio written:", os.path.getsize(temp_base), "bytes")

    model_path = os.path.join(os.path.dirname(__file__), "uploads", "rvc_models", "default_voice.pth")
    if os.path.exists(model_path):
        rvc_bytes = RVCPipelineService.convert_speech(temp_base, model_path, f0_pitch_shift=4)
        if rvc_bytes:
            print("=== RVC EMOTIONAL HUMAN VOICE AUDIO BYTES ===", len(rvc_bytes))
        else:
            print("RVC returned None")

if __name__ == "__main__":
    asyncio.run(main())
