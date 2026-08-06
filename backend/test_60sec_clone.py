import os
import sys
import json
import urllib.request
import librosa
import soundfile as sf
import whisper

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
VOICES_DIR = os.path.join(BACKEND_DIR, "uploads", "voices")
os.makedirs(VOICES_DIR, exist_ok=True)

wav_path = r"b:\youtubeProjects\Buzzcaf Media\60sec.wav"
print(f"[TEST 60SEC] Checking file: {wav_path} (exists: {os.path.exists(wav_path)})")

# 1. Transcribe 60sec.wav using Whisper
print("[TEST 60SEC] Transcribing 60sec.wav with Whisper...")
model = whisper.load_model("base")
result = model.transcribe(wav_path)
full_transcript = result["text"].strip()
print(f"[TEST 60SEC] Full Transcript:\n{full_transcript}\n")

# 2. Trim & Normalize to 12s reference audio for F5-TTS
audio, sr = librosa.load(wav_path, sr=24000, mono=True)
# Take first 12 seconds for optimal flow matching reference
audio_12s = audio[: 24000 * 12]
ref_norm_path = os.path.join(VOICES_DIR, "60sec_ref_12s.wav")
sf.write(ref_norm_path, audio_12s, 24000, subtype='PCM_16')
print(f"[TEST 60SEC] Normalized 12s ref audio saved to: {ref_norm_path}")

# Get transcript for the first 12s
res_12s = model.transcribe(ref_norm_path)
ref_text_12s = res_12s["text"].strip()
print(f"[TEST 60SEC] 12s Reference Transcript:\n{ref_text_12s}\n")

# 3. Test F5-TTS synthesis with default Hindi text
gen_text = "hi, mera naam sudhanshu hai aur main ek voice agent hoon. main dekhna chahta hoon ki voice cloning kitni achhi hui hai"

payload = {
    "text": gen_text,
    "speaker_wav": ref_norm_path,
    "ref_text": ref_text_12s,
    "nfe_step": 32
}

data = json.dumps(payload).encode("utf-8")
req = urllib.request.Request("http://127.0.0.1:8097/synthesize", data=data, headers={"Content-Type": "application/json"})

try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        audio_bytes = resp.read()
        out_wav = os.path.join(VOICES_DIR, "60sec_f5_cloned_output.wav")
        with open(out_wav, "wb") as f:
            f.write(audio_bytes)
        print(f"[TEST 60SEC] F5-TTS Synthesis Successful! Output file: {out_wav} ({len(audio_bytes)} bytes)")
except Exception as e:
    print(f"[TEST 60SEC] F5-TTS Synthesis Error: {e}")
