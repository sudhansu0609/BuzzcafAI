import asyncio
import edge_tts

async def main():
    text = "Uff! Achaa, suno... Aaj ka din toh bahut mast hone wala hai! Tum batao, kya plan hai?"
    
    # Test valid Hz pitch syntax
    comm_expr = edge_tts.Communicate(text, voice="en-IN-NeerjaExpressiveNeural", pitch="+25Hz", rate="-5%")
    audio_expr = b""
    async for chunk in comm_expr.stream():
        if chunk["type"] == "audio":
            audio_expr += chunk["data"]
            
    print("NeerjaExpressiveNeural valid Hz pitch audio bytes:", len(audio_expr))

if __name__ == "__main__":
    asyncio.run(main())
