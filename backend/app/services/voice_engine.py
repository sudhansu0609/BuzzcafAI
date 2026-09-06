# Buzzcaf AI - Voice Engine Service (STT & Zero-Shot Voice Cloning TTS)
import os
import uuid
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger("buzzcaf_ai.voice_engine")

VOICES_STORAGE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "projects",
    "voice_profiles"
)

class VoiceEngineService:
    def __init__(self):
        os.makedirs(VOICES_STORAGE_DIR, exist_ok=True)

    def process_voice_cloning_sample(
        self,
        voice_name: str,
        sample_audio_bytes: bytes,
        filename: str = "sample.wav"
    ) -> Dict[str, Any]:
        """Save reference voice audio clip and extract F5-TTS / XTTS v2 voice embedding profile."""
        voice_id = f"cloned-voice-{uuid.uuid4().hex[:8]}"
        voice_dir = os.path.join(VOICES_STORAGE_DIR, voice_id)
        os.makedirs(voice_dir, exist_ok=True)

        audio_path = os.path.join(voice_dir, filename)
        with open(audio_path, "wb") as f:
            f.write(sample_audio_bytes)

        # The reference clip is stored, but no embedding is extracted yet --
        # say so rather than reporting the profile as ready to synthesize.
        metadata = {
            "id": voice_id,
            "name": voice_name,
            "audioPath": audio_path,
            "sampleFilename": filename,
            "status": "sample_stored",
            "model": None,
            "detail": "Reference clip saved. Voice embedding extraction is not implemented yet.",
            "createdAt": datetime.now(timezone.utc).isoformat()
        }

        with open(os.path.join(voice_dir, "profile.json"), "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Cloned voice profile created: {voice_name} (ID: {voice_id})")
        return metadata

    def list_voice_profiles(self) -> Dict[str, Any]:
        profiles = []
        if os.path.exists(VOICES_STORAGE_DIR):
            for d in os.listdir(VOICES_STORAGE_DIR):
                meta_path = os.path.join(VOICES_STORAGE_DIR, d, "profile.json")
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, "r", encoding="utf-8") as f:
                            profiles.append(json.load(f))
                    except Exception:
                        pass
        return {"profiles": profiles, "count": len(profiles)}

    def synthesize_cloned_speech(
        self,
        text: str,
        voice_id: str = "default-voice",
        agent_name: str = "AI Agent"
    ) -> Dict[str, Any]:
        """Synthesize TTS speech in the agent's cloned voice profile.

        Not implemented yet: no TTS engine is wired up. This deliberately
        returns no audioUrl -- an earlier version returned a URL for a file
        that was never written, so every playback attempt 404'd. The client
        should fall back to browser speech synthesis while status is
        'not_implemented'.
        """
        return {
            "status": "not_implemented",
            "text": text,
            "voiceId": voice_id,
            "agentName": agent_name,
            "audioUrl": None,
            "sampleRate": 24000,
            "engine": None,
            "detail": "Server-side voice cloning is not wired up; using browser speech instead."
        }

voice_engine_service = VoiceEngineService()
