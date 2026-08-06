import os
import sys
import json
import asyncio
import edge_tts
import torch
import urllib.request
import whisper

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
VOICES_DIR = os.path.join(BACKEND_DIR, "uploads", "voices")
ref_wav = r"b:\youtubeProjects\Buzzcaf Media\60sec.wav"

text = "hi mera nam sudhansu hai aur main ek voice agent hu. main dekhna chahta hu ki voice cloning kitni achi hui hai"
base_mp3 = os.path.join(VOICES_DIR, "base_swara.mp3")
base_wav = os.path.join(VOICES_DIR, "base_swara.wav")

# 1. Generate base speech with hi-IN-SwaraNeural
async def gen_base():
    c = edge_tts.Communicate(text, voice="hi-IN-SwaraNeural")
    await c.save(base_mp3)

asyncio.run(gen_base())

# Convert base_mp3 to 24kHz WAV for OpenVoice
import librosa
import soundfile as sf
y, sr = librosa.load(base_mp3, sr=24000)
sf.write(base_wav, y, 24000, subtype='PCM_16')
print(f"[TEST OPENVOICE] Base WAV saved: {base_wav} ({os.path.getsize(base_wav)} bytes)")

# 2. Call OpenVoice Tone Color Converter on port 8097
payload = {
    "base_audio": base_wav,
    "reference_audio": ref_wav
}

data = json.dumps(payload).encode("utf-8")
req = urllib.request.Request("http://127.0.0.1:8097/convert", data=data, headers={"Content-Type": "application/json"})

try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        audio_bytes = resp.read()
        cloned_wav = os.path.join(VOICES_DIR, "openvoice_cloned_sudhanshu.wav")
        with open(cloned_wav, "wb") as f:
            f.write(audio_bytes)
        print(f"[TEST OPENVOICE] SUCCESS! Cloned WAV saved: {cloned_wav} ({len(audio_bytes)} bytes)")
        
        # 3. Verify output with Whisper AI
        m = whisper.load_model("base")
        res = m.transcribe(cloned_wav)
        print(f"[WHISPER VERIFICATION OF OPENVOICE CLONE]:\n{res['text'].strip()}")
except Exception as e:
    print(f"[TEST OPENVOICE] Error: {e}")
