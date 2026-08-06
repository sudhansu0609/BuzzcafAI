import asyncio
from app.services.voice_engine import VoiceEngineService

async def main():
    audio_bytes, media_type = await VoiceEngineService.generate_speech_audio(
        text="Haan ji, main soch rahi hu! Ek minute, thoda wait kijiye. Aaj ka mood kaisa hai aapka?",
        voice_base="hi-IN-SwaraNeural"
    )
    print("=== EXPRESSIVE SSML AUDIO TEST ===")
    print("Media Type:", media_type)
    print("Audio Data Size:", len(audio_bytes), "bytes")
    print("=================================")

if __name__ == "__main__":
    asyncio.run(main())
