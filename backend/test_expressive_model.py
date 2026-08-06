import asyncio
import edge_tts

async def main():
    text = "Uff! Achaa, suno... Aaj ka din toh bahut mast hone wala hai! Tum batao, kya plan hai?"
    
    # Test Neerja Expressive
    comm_expr = edge_tts.Communicate(text, voice="en-IN-NeerjaExpressiveNeural", pitch="+5%", rate="-4%")
    audio_expr = b""
    async for chunk in comm_expr.stream():
        if chunk["type"] == "audio":
            audio_expr += chunk["data"]
            
    print("NeerjaExpressiveNeural audio bytes:", len(audio_expr))

if __name__ == "__main__":
    asyncio.run(main())
