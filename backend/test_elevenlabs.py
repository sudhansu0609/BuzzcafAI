import os

key = os.getenv("ELEVENLABS_API_KEY")
print("ELEVENLABS_API_KEY in env:", key if key else "NOT_FOUND")
