import librosa
import soundfile as sf
import numpy as np

def convert_voice(base_wav_path: str, reference_wav_path: str, output_wav_path: str, alpha: float = 0.85):
    # 1. Load reference voice sample
    y_ref, sr = librosa.load(reference_wav_path, sr=22050)
    if len(y_ref.shape) > 1:
        y_ref = y_ref.mean(axis=1)

    # 2. Extract reference spectral envelope & pitch
    S_ref = np.abs(librosa.stft(y_ref))
    env_ref = np.mean(S_ref, axis=1) + 1e-6
    
    f0_ref, _, _ = librosa.pyin(y_ref, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C6'), sr=sr)
    valid_f0_ref = f0_ref[~np.isnan(f0_ref)]
    median_f0_ref = float(np.median(valid_f0_ref)) if len(valid_f0_ref) > 0 else 160.0

    # 3. Load base synthesized speech
    y_base, _ = librosa.load(base_wav_path, sr=sr)
    if len(y_base.shape) > 1:
        y_base = y_base.mean(axis=1)

    f0_base, _, _ = librosa.pyin(y_base, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C6'), sr=sr)
    valid_f0_base = f0_base[~np.isnan(f0_base)]
    median_f0_base = float(np.median(valid_f0_base)) if len(valid_f0_base) > 0 else 160.0

    # 4. Pitch shift to match reference voice fundamental frequency
    semitones = float(12 * np.log2(median_f0_ref / max(median_f0_base, 50.0)))
    if abs(semitones) > 0.3:
        y_base = librosa.effects.pitch_shift(y_base, sr=sr, n_steps=semitones)

    # 5. Apply STFT spectral envelope morphing (transfer target vocal timbre & formants)
    stft_base = librosa.stft(y_base)
    mag_base = np.abs(stft_base)
    phase_base = np.angle(stft_base)

    env_base = np.mean(mag_base, axis=1) + 1e-6
    
    # Gain filter ratio
    gain_filter = (env_ref / env_base) ** alpha
    gain_filter = np.clip(gain_filter, 0.2, 4.0)

    # Apply spectral gain envelope to each time frame
    mag_morphed = mag_base * gain_filter[:, np.newaxis]
    stft_morphed = mag_morphed * np.exp(1j * phase_base)
    
    y_out = librosa.istft(stft_morphed)
    max_val = np.max(np.abs(y_out))
    if max_val > 0:
        y_out = y_out / max_val * 0.95

    sf.write(output_wav_path, y_out, sr)
    print(f"[SUCCESS] Successfully converted voice to target speaker timbre: {output_wav_path}")

if __name__ == "__main__":
    convert_voice("uploads/voices/test_output.wav", "uploads/voices/voice-03a26a38_voice1.wav", "uploads/voices/morphed_test.wav")
