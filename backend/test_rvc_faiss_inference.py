import os
import sys
import json
import asyncio
import edge_tts
import torch
import librosa
import soundfile as sf
import whisper

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
VOICES_DIR = os.path.join(BACKEND_DIR, "uploads", "voices")
RVC_MODELS_DIR = os.path.join(BACKEND_DIR, "uploads", "rvc_models")
index_path = os.path.join(VOICES_DIR, "sudhanshu_voice.index")

# 1. Generate base speech with hi-IN-SwaraNeural
text = "हाय मेरा नाम सुधांशु है और मैं एक वॉइस एजेंट हूं। मैं देखना चाहता हूं कि वॉइस क्लोनिंग कितनी अच्छी हुई है।"
base_mp3 = os.path.join(VOICES_DIR, "rvc_base_swara.mp3")
base_wav = os.path.join(VOICES_DIR, "rvc_base_swara.wav")

async def gen_base():
    c = edge_tts.Communicate(text, voice="hi-IN-SwaraNeural")
    await c.save(base_mp3)

asyncio.run(gen_base())

# Convert to 16kHz WAV for RVC
y, sr = librosa.load(base_mp3, sr=16000)
sf.write(base_wav, y, 16000, subtype='PCM_16')
print(f"[RVC TEST] Base audio saved: {base_wav} ({os.path.getsize(base_wav)} bytes)")

# 2. Call OpenVoice V2 Tone Color Converter with FAISS feature retrieval
ref_wav = r"b:\youtubeProjects\Buzzcaf Media\60sec.wav"
payload = {
    "base_audio": base_wav,
    "reference_audio": ref_wav
}

data = json.dumps(payload).encode("utf-8")
import urllib.request
req = urllib.request.Request("http://127.0.0.1:8097/convert", data=data, headers={"Content-Type": "application/json"})

try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        audio_bytes = resp.read()
        out_file = os.path.join(VOICES_DIR, "rvc_faiss_cloned_output.wav")
        with open(out_file, "wb") as f:
            f.write(audio_bytes)
        print(f"[RVC TEST] SUCCESS! Saved FAISS-retrieved cloned voice to: {out_file} ({len(audio_bytes)} bytes)")
        
        # 3. Whisper verification
        m = whisper.load_model("base")
        res = m.transcribe(out_file)
        print(f"[WHISPER VERIFICATION OF RVC CLONE]:\n{res['text'].encode('utf-8').decode('utf-8')}")
except Exception as e:
    print(f"[RVC TEST] Error: {e}")
