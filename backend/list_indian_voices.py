import asyncio
import edge_tts

async def main():
    voices = await edge_tts.list_voices()
    indian_voices = [v for v in voices if "IN" in v["ShortName"]]
    print("=== AVAILABLE INDIAN ACCENT NEURAL VOICES ===")
    for v in indian_voices:
        print(f"Name: {v['ShortName']} | Gender: {v['Gender']} | StyleList: {v.get('VoiceTag', {}).get('VoicePersonalities', [])}")

if __name__ == "__main__":
    asyncio.run(main())
