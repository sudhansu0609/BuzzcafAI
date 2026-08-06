import os
import sys
import json
import asyncio
import edge_tts
import torch
import librosa
import soundfile as sf
import urllib.request
import whisper

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
VOICES_DIR = os.path.join(BACKEND_DIR, "uploads", "voices")
ref_wav = r"b:\youtubeProjects\Buzzcaf Media\60sec.wav"

# 1. Base speech generation with hi-IN-MadhurNeural (MALE Hindi voice base)
text = "हाय मेरा नाम सुधांशु है और मैं एक वॉइस एजेंट हूं। मैं देखना चाहता हूं कि वॉइस क्लोनिंग कितनी अच्छी हुई है।"

async def gen_base():
    c = edge_tts.Communicate(text, voice="hi-IN-MadhurNeural")
    base_mp3 = os.path.join(VOICES_DIR, "madhur_base.mp3")
    await c.save(base_mp3)
    y, sr = librosa.load(base_mp3, sr=24000)
    base_wav = os.path.join(VOICES_DIR, "madhur_base.wav")
    sf.write(base_wav, y, 24000, subtype='PCM_16')
    return base_wav

base_wav = asyncio.run(gen_base())
print(f"[MADHUR MALE BASE TEST] Generated base WAV with hi-IN-MadhurNeural: {base_wav} ({os.path.getsize(base_wav)} bytes)")

# 2. Convert tone color using OpenVoice V2 on GPU
payload = {
    "base_audio": base_wav,
    "reference_audio": ref_wav
}
data = json.dumps(payload).encode("utf-8")
req = urllib.request.Request("http://127.0.0.1:8097/convert", data=data, headers={"Content-Type": "application/json"})

print(f"[MADHUR MALE BASE TEST] Morphing male base into Sudhanshu's voice via OpenVoice V2...")
with urllib.request.urlopen(req, timeout=60) as resp:
    audio_bytes = resp.read()

out_file = os.path.join(VOICES_DIR, "sudhanshu_male_cloned_final.wav")
with open(out_file, "wb") as f:
    f.write(audio_bytes)

print(f"[MADHUR MALE BASE TEST] SUCCESS! Saved cloned male audio: {out_file} ({len(audio_bytes)} bytes)")

# 3. Whisper verification
m = whisper.load_model("base")
res = m.transcribe(out_file)
print(f"[WHISPER VERIFICATION OF MALE CLONE]:\n{res['text'].encode('utf-8').decode('utf-8')}")
