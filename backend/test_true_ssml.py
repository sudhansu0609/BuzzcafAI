import asyncio
import edge_tts

async def main():
    text = "Uff! Achaa, suno... Aaj ka din toh bahut mast hone wala hai! Tum batao, kya plan hai?"
    
    # 1. Test raw text vs SSML
    communicate_raw = edge_tts.Communicate(text, voice="hi-IN-SwaraNeural", pitch="+5%", rate="-4%")
    audio_raw = b""
    async for chunk in communicate_raw.stream():
        if chunk["type"] == "audio":
            audio_raw += chunk["data"]
            
    print("Raw text audio bytes:", len(audio_raw))

if __name__ == "__main__":
    asyncio.run(main())
