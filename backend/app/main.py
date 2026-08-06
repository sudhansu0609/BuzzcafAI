from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.api.agents_api import router as agents_router
from app.api.auth_api import router as auth_router
from app.services.voice_engine import VoiceEngineService
import asyncio


def _preload_all_engines():
    """Pre-load all TTS engines and start microservices to eliminate cold-start delays."""
    print("[MidnightBuzz] === Pre-loading all voice engines ===")
    
    # 1. Start XTTS server (has ensure_server function)
    VoiceEngineService.ensure_xtts_server()
    
    # 2. Pre-load Kokoro ONNX model (fast, ~2-3s)
    try:
        kokoro = VoiceEngineService._get_kokoro_tts()
        if kokoro:
            print("[MidnightBuzz] [OK] Kokoro ONNX pre-loaded")
        else:
            print("[MidnightBuzz] [WARN] Kokoro ONNX not available")
    except Exception as e:
        print(f"[MidnightBuzz] [WARN] Kokoro preload failed: {e}")
    
    # 3. Warm up Edge TTS with a silent ping (forces first connection)
    try:
        import edge_tts
        async def _ping():
            comm = edge_tts.Communicate("Thank you", voice="en-IN-PrabhatNeural")
            async for chunk in comm.stream():
                pass
        asyncio.get_event_loop().run_until_complete(_ping())
        print("[MidnightBuzz] [OK] Edge TTS warmed up")
    except Exception as e:
        print(f"[MidnightBuzz] [WARN] Edge TTS warmup failed: {e}")
    
    print("[MidnightBuzz] === Pre-loading complete ===")


@asynccontextmanager
async def lifespan(app):
    # Pre-load everything synchronously before accepting requests
    _preload_all_engines()
    yield


app = FastAPI(
    title="MidnightBuzz API Server",
    description="Backend service for Standalone Agent Creator & Group Voice Chat",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agents_router)
app.include_router(auth_router)

@app.get("/")
def root():
    return {
        "status": "online",
        "app": "MidnightBuzz Backend API",
        "version": "1.0.0",
        "docs": "/docs"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8095, reload=True)
