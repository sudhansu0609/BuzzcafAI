import os
import asyncio
import edge_tts
import whisper

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
VOICES_DIR = os.path.join(BACKEND_DIR, "uploads", "voices")

text = "hi mera nam sudhansu hai aur main ek voice agent hu. main dekhna chahta hu ki voice cloning kitni achi hui hai"
out_wav = os.path.join(VOICES_DIR, "test_swara_hindi.mp3")

async def generate():
    communicate = edge_tts.Communicate(text, voice="hi-IN-SwaraNeural")
    await communicate.save(out_wav)
    print(f"[EDGE TTS TEST] Saved Swara Neural audio to: {out_wav} ({os.path.getsize(out_wav)} bytes)")

asyncio.run(generate())

# Transcribe with Whisper to verify 100% exact text matching
m = whisper.load_model("base")
res = m.transcribe(out_wav)
print(f"[WHISPER VERIFICATION OF SWARA HINDI]:\n{res['text'].strip()}")
