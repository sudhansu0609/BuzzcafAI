import os
import sys
import uuid
import torch
from typing import Optional, Any
try:
    import fairseq.data.dictionary
    torch.serialization.add_safe_globals([fairseq.data.dictionary.Dictionary])
except Exception:
    pass

# Ensure Fairseq / Hydra compatibility patches are active in memory
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VOICES_DIR = os.path.join(BACKEND_DIR, "uploads", "voices")
RVC_MODELS_DIR = os.path.join(BACKEND_DIR, "uploads", "rvc_models")
os.makedirs(RVC_MODELS_DIR, exist_ok=True)

try:
    from rvc_python.infer import RVCInference
    RVC_AVAILABLE = True
except Exception as e:
    print(f"[RVCPipeline] rvc_python import error: {e}")
    RVC_AVAILABLE = False


class RVCPipelineService:
    _instances = {}

    @staticmethod
    def get_inference(model_path: str, device: str = "cuda:0") -> Optional[Any]:
        if not RVC_AVAILABLE:
            print("[RVCPipeline] rvc_python is not available.")
            return None
        
        if not torch.cuda.is_available():
            device = "cpu:0"

        if model_path in RVCPipelineService._instances:
            return RVCPipelineService._instances[model_path]

        try:
            rvc = RVCInference(device=device)
            rvc.load_model(model_path)
            RVCPipelineService._instances[model_path] = rvc
            print(f"[RVCPipeline] [OK] Loaded RVC model: {os.path.basename(model_path)} on {device}")
            return rvc
        except Exception as e:
            print(f"[RVCPipeline] Error loading model {model_path}: {e}")
            return None

    @staticmethod
    def convert_speech(base_wav_path: str, model_path: str, f0_pitch_shift: int = 0) -> Optional[bytes]:
        """Runs RVC Voice Conversion over input base audio on RTX 5060 Ti GPU."""
        if not os.path.exists(base_wav_path) or not os.path.exists(model_path):
            print(f"[RVCPipeline] Missing base audio or model path: {base_wav_path} / {model_path}")
            return None

        rvc = RVCPipelineService.get_inference(model_path)
        if not rvc:
            return None

        try:
            out_filename = f"rvc_out_{uuid.uuid4().hex[:6]}.wav"
            out_filepath = os.path.join(VOICES_DIR, out_filename)
            
            rvc.set_params(f0up_key=f0_pitch_shift, f0method="rmvpe")
            rvc.infer_file(base_wav_path, out_filepath)

            if os.path.exists(out_filepath) and os.path.getsize(out_filepath) > 0:
                try:
                    import librosa
                    import soundfile as sf
                    y, _ = librosa.load(out_filepath, sr=44100)
                    resampled_path = out_filepath.replace(".wav", "_44k.wav")
                    sf.write(resampled_path, y, 44100, subtype='PCM_16')
                    target_path = resampled_path if os.path.exists(resampled_path) else out_filepath
                except Exception as ex:
                    print(f"[RVCPipeline] Resample warning: {ex}")
                    target_path = out_filepath

                with open(target_path, "rb") as f:
                    audio_bytes = f.read()
                try:
                    os.remove(out_filepath)
                    if os.path.exists(resampled_path):
                        os.remove(resampled_path)
                except Exception:
                    pass
                print(f"[RVCPipeline] [OK] RVC converted audio (44.1kHz PCM 16-bit): {len(audio_bytes)} bytes")
                return audio_bytes
        except Exception as ex:
            print(f"[RVCPipeline] RVC conversion error: {ex}")
        return None
