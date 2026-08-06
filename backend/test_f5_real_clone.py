import os
import sys
import torch
import soundfile as sf
import whisper

# Patch torch.load
_orig_load = torch.load
def _patched_load(*args, **kwargs):
    kwargs["weights_only"] = False
    return _orig_load(*args, **kwargs)
torch.load = _patched_load

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
VOICES_DIR = os.path.join(BACKEND_DIR, "uploads", "voices")
ref_wav = r"b:\youtubeProjects\Buzzcaf Media\60sec.wav"
clean_ref = os.path.join(VOICES_DIR, "60sec_ref_12s.wav")
target_ref = clean_ref if os.path.exists(clean_ref) else ref_wav

print(f"[F5-TTS TEST] CUDA Available: {torch.cuda.is_available()} ({torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'})")

# 1. Transcribe reference sample for 100% F5-TTS alignment
print("[F5-TTS TEST] Transcribing reference audio for F5-TTS alignment...")
m_w = whisper.load_model("tiny")
res_w = m_w.transcribe(target_ref)
ref_text = res_w.get("text", "").strip()
print(f"[F5-TTS TEST] Reference Transcript: '{ref_text}'")

# 2. Synthesize voice clone using F5-TTS Flow Matching API
from f5_tts.api import F5TTS

print("[F5-TTS TEST] Initializing F5-TTS Flow Matching API...")
f5tts = F5TTS()

# Hinglish / Hindi text for test
text = "hi mera nam sudhansu hai aur main ek voice agent hu. main dekhna chahta hu ki voice cloning kitni achi hui hai"
out_wav = os.path.join(VOICES_DIR, "f5_sudhanshu_real_clone.wav")

print(f"[F5-TTS TEST] Generating F5-TTS speech clone for '{text}'...")
wav, sr, spec = f5tts.infer(
    ref_file=target_ref,
    ref_text=ref_text,
    gen_text=text,
    file_wave=out_wav
)

print(f"[F5-TTS TEST] SUCCESS! Saved F5-TTS cloned voice to: {out_wav} ({os.path.getsize(out_wav)} bytes)")

# 3. Whisper verification of output
m = whisper.load_model("base")
res = m.transcribe(out_wav)
print(f"[WHISPER VERIFICATION OF F5-TTS REAL VOICE CLONE]:\n{res['text'].encode('utf-8').decode('utf-8')}")
