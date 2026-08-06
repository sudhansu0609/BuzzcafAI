import os
import sys
import json
import asyncio
import edge_tts
import torch
import urllib.request
import librosa
import soundfile as sf
import whisper

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
VOICES_DIR = os.path.join(BACKEND_DIR, "uploads", "voices")
ref_wav = os.path.join(VOICES_DIR, "60sec_ref_12s.wav")

if not os.path.exists(ref_wav):
    ref_wav = r"b:\youtubeProjects\Buzzcaf Media\60sec.wav"

hindi_text = "हाय मेरा नाम सुधांशु है और मैं एक वॉइस एजेंट हूं। मैं देखना चाहता हूं कि वॉइस क्लोनिंग कितनी अच्छी हुई है।"

base_mp3 = os.path.join(VOICES_DIR, "base_devanagari_swara.mp3")
base_wav = os.path.join(VOICES_DIR, "base_devanagari_swara.wav")

# 1. Generate base speech with Edge-TTS using native Devanagari Hindi
async def gen_base():
    c = edge_tts.Communicate(hindi_text, voice="hi-IN-SwaraNeural")
    await c.save(base_mp3)

asyncio.run(gen_base())

# Convert MP3 to 24kHz PCM WAV
y, sr = librosa.load(base_mp3, sr=24000)
sf.write(base_wav, y, 24000, subtype='PCM_16')
print(f"[TEST HINDI OPENVOICE] Base Devanagari WAV saved: {base_wav} ({os.path.getsize(base_wav)} bytes)")

# 2. Call OpenVoice V2 Tone Color Converter
payload = {
    "base_audio": base_wav,
    "reference_audio": ref_wav
}

data = json.dumps(payload).encode("utf-8")
req = urllib.request.Request("http://127.0.0.1:8097/convert", data=data, headers={"Content-Type": "application/json"})

try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        audio_bytes = resp.read()
        cloned_wav = os.path.join(VOICES_DIR, "openvoice_cloned_hindi_sudhanshu.wav")
        with open(cloned_wav, "wb") as f:
            f.write(audio_bytes)
        print(f"[TEST HINDI OPENVOICE] SUCCESS! Cloned Devanagari WAV: {cloned_wav} ({len(audio_bytes)} bytes)")
        
        # 3. Whisper verification
        m = whisper.load_model("base")
        res = m.transcribe(cloned_wav)
        print(f"[WHISPER VERIFICATION OF DEVANAGARI HINDI CLONE]:\n{res['text'].strip()}")
except Exception as e:
    print(f"[TEST HINDI OPENVOICE] Error: {e}")
