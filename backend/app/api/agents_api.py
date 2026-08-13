from fastapi import APIRouter, HTTPException, File, UploadFile, Query, Response, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import os
import asyncio
import json
import base64

from app.services.agents_registry import AgentsRegistry
from app.services.local_llm import LocalLLMService
from app.services.voice_engine import VoiceEngineService

router = APIRouter(prefix="/api")
registry = AgentsRegistry()

class VoiceProfileModel(BaseModel):
    voiceId: str
    name: str
    samplePath: Optional[str] = None
    pitch: float = 1.0
    rate: float = 1.0
    cloned: bool = False

class AgentModel(BaseModel):
    id: str
    name: str
    role: str
    avatar: str
    avatarIcon: str = "🤖"
    personaTag: str = "General"
    systemPrompt: str
    temperature: float = 0.7
    topP: float = 0.9
    maxTokens: int = 1024
    responseStyle: str = "Concise"
    responseLanguage: Optional[str] = "Hinglish"
    modelMapping: str = "llama-3.2-3b"
    voiceProfile: Optional[VoiceProfileModel] = None
    createdAt: Optional[str] = None
    avatarImage: Optional[str] = None
    voiceEnabled: Optional[bool] = True
    ownerId: Optional[str] = None

class ChatRequestModel(BaseModel):
    agentId: str
    userMessage: str
    chatHistory: List[Dict[str, str]] = []
    groupAgentIds: Optional[List[str]] = None

class ChatRequest(BaseModel):
    agent_id: str
    message: str
    chat_history: List[Dict[str, str]] = []
    model: Optional[str] = None

@router.get("/agents", response_model=List[Dict[str, Any]])
def get_agents(x_user_id: Optional[str] = Header(None)):
    user_id = x_user_id or "user-default"
    return registry.get_all_agents(user_id)

@router.get("/agents/{agent_id}", response_model=Dict[str, Any])
def get_agent(agent_id: str, x_user_id: Optional[str] = Header(None)):
    user_id = x_user_id or "user-default"
    agent = registry.get_agent_by_id(agent_id, user_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent

@router.post("/agents", response_model=Dict[str, Any])
def create_agent(agent: AgentModel, x_user_id: Optional[str] = Header(None)):
    user_id = x_user_id or "user-default"
    agent_dict = agent.dict()
    agent_dict["ownerId"] = user_id
    return registry.save_agent(agent_dict, user_id)

@router.put("/agents/{agent_id}", response_model=Dict[str, Any])
def update_agent(agent_id: str, agent: AgentModel, x_user_id: Optional[str] = Header(None)):
    user_id = x_user_id or "user-default"
    agent_dict = agent.dict()
    agent_dict["id"] = agent_id
    agent_dict["ownerId"] = user_id
    return registry.save_agent(agent_dict, user_id)

@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: str, x_user_id: Optional[str] = Header(None)):
    user_id = x_user_id or "user-default"
    success = registry.delete_agent(agent_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Agent not found or access denied")
    return {"status": "success", "deletedId": agent_id}

@router.get("/models")
def get_models():
    return LocalLLMService.get_available_models()

@router.post("/agents/clone-voice")
async def clone_voice(file: UploadFile = File(...)):
    contents = await file.read()
    res = VoiceEngineService.process_voice_sample(file.filename, contents)
    return res

@router.get("/uploads/voices/{filename}")
def get_voice_file(filename: str):
    import os
    filepath = os.path.join(VoiceEngineService.VOICES_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Audio file not found")
    with open(filepath, "rb") as f:
        content = f.read()
    media_type = "audio/wav" if filename.endswith(".wav") else "audio/mpeg"
    return Response(content=content, media_type=media_type)

@router.post("/chat/completions")
def chat_completion(req: ChatRequestModel, x_user_id: Optional[str] = Header(None)):
    user_id = x_user_id or "user-default"
    agent = registry.get_agent_by_id(req.agentId, user_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Build system prompt — inject Hindi Devanagari instruction if responseLanguage is 'Hindi'
    base_system_prompt = agent.get("systemPrompt", "")
    response_language = agent.get("responseLanguage", "Hinglish")
    
    if response_language == "Hindi":
        import re
        base_system_prompt = re.sub(r'\bHinglish\b', 'Hindi Devanagari script', base_system_prompt, flags=re.IGNORECASE)
        base_system_prompt = re.sub(r'\bhinglish\b', 'Hindi Devanagari script', base_system_prompt, flags=re.IGNORECASE)
        
        hindi_instruction = (
            "CRITICAL MANDATORY SYSTEM INSTRUCTION (STRICT OVERRIDE):\n"
            "You MUST write your ENTIRE response using HINDI DEVANAGARI SCRIPT ONLY (हिंदी देवनागरी लिपि).\n"
            "DO NOT write in Hinglish or English alphabet! Write all words in Devanagari script (e.g., 'अरे! क्या हाल है? मैं बहुत अच्छी हूँ!').\n"
            "Even slang words must be written in Devanagari script!\n"
            "DO NOT OUTPUT A SINGLE WORD IN ENGLISH/HINGLISH ALPHABET."
        )
        base_system_prompt = f"{hindi_instruction}\n\n{base_system_prompt}\n\n{hindi_instruction}"

    response_text = LocalLLMService.generate_chat_response(
        system_prompt=base_system_prompt,
        user_message=req.userMessage,
        chat_history=req.chatHistory,
        model_name=agent.get("modelMapping", "llama-3.2-3b"),
        temperature=agent.get("temperature", 0.7),
        top_p=agent.get("topP", 0.9),
        max_tokens=agent.get("maxTokens", 1024)
    )

    # Optional multi-agent group chat additions
    group_responses = []
    if req.groupAgentIds:
        for g_id in req.groupAgentIds:
            if g_id != req.agentId:
                g_agent = registry.get_agent_by_id(g_id)
                if g_agent:
                    g_text = LocalLLMService.generate_chat_response(
                        system_prompt=g_agent.get("systemPrompt", ""),
                        user_message=f"Agent '{agent['name']}' said: '{response_text}'. Add your perspective as '{g_agent['role']}'.",
                        chat_history=req.chatHistory,
                        model_name=g_agent.get("modelMapping", "llama-3.2-3b"),
                        temperature=g_agent.get("temperature", 0.7)
                    )
                    group_responses.append({
                        "agentId": g_agent["id"],
                        "agentName": g_agent["name"],
                        "avatar": g_agent["avatar"],
                        "avatarIcon": g_agent.get("avatarIcon", "🤖"),
                        "text": g_text
                    })

    return {
        "agentId": agent["id"],
        "agentName": agent["name"],
        "avatar": agent["avatar"],
        "avatarIcon": agent.get("avatarIcon", "🤖"),
        "text": response_text,
        "groupResponses": group_responses
    }

@router.get("/voice-models")
def get_voice_models():
    return VoiceEngineService.get_voice_models()

@router.get("/tts/stream")
async def tts_stream(
    text: str,
    pitch: float = 1.0,
    rate: float = 1.0,
    sample_path: Optional[str] = None,
    voice_model: Optional[str] = None,
    agent_id: Optional[str] = None,
    clone_method: str = "f5",
    fast_mode: bool = True,
    x_user_id: Optional[str] = Header(None)
):
    voice_base = voice_model
    if agent_id:
        # Look the agent up as its owner, the same way every other endpoint
        # does. This used to pass the literal string "all", which the registry
        # matches against ownerId — so it resolved nothing, and every cloned
        # agent addressed by id alone got answered in a stock Edge voice.
        agent = registry.get_agent_by_id(agent_id, x_user_id or "user-default")
        if agent and agent.get("voiceProfile"):
            vp = agent["voiceProfile"]
            # Any recorded sample means "speak as this person" — matching the
            # /chat/stream path, which never required the `cloned` flag. Gating
            # on it here made replay use a stock voice for the same agent that
            # streams in its clone.
            if not sample_path and vp.get("samplePath"):
                sample_path = vp.get("samplePath")

            if not voice_base:
                is_female = any(fem in (agent.get("name", "") + " " + agent.get("role", "")).lower() for fem in ["shilpi", "ananya", "swara", "neerja", "female", "woman", "girl", "sarah", "bella"])
                voice_base = vp.get("voiceId") or vp.get("clonedVoiceBase") or ("kokoro-af_bella" if is_female else "kokoro-am_adam")

    audio_bytes, media_type, engine = await VoiceEngineService.generate_speech_audio(
        text, pitch=pitch, rate=rate, sample_path=sample_path, voice_base=voice_base, clone_method=clone_method, fast_mode=fast_mode
    )
    return Response(content=audio_bytes, media_type=media_type, headers={"X-Voice-Engine": engine})

@router.post("/settings/elevenlabs")
def save_elevenlabs_key(data: Dict[str, str]):
    key = data.get("apiKey", "").strip()
    if key:
        os.environ["ELEVENLABS_API_KEY"] = key
    return {"status": "success", "active": bool(os.getenv("ELEVENLABS_API_KEY"))}

@router.get("/settings/elevenlabs")
def get_elevenlabs_status():
    key = os.getenv("ELEVENLABS_API_KEY")
    return {
        "active": bool(key),
        "maskedKey": f"{key[:4]}...{key[-4:]}" if key and len(key) > 8 else None
    }

@router.post("/stt")
async def speech_to_text(file: UploadFile = File(...)):
    audio_bytes = await file.read()
    text = VoiceEngineService.transcribe_audio(audio_bytes)
    return {"text": text}

@router.post("/chat/stream")
async def chat_stream_parallel_tts(request: ChatRequest, x_user_id: str = Header(default="anonymous")):
    """SSE endpoint: streams LLM tokens AND triggers parallel TTS per sentence.
    
    Uses thread pools for LLM streaming and TTS workers so both text tokens 
    and sentence audio chunks are delivered at maximum speed (< 1s latency).
    """
    user_id = x_user_id or "user-default"
    agent = registry.get_agent_by_id(request.agent_id, user_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    system_prompt = agent.get("systemPrompt", "You are a helpful assistant.")
    response_language = agent.get("responseLanguage", "Hinglish")
    
    if response_language == "Hindi":
        import re
        system_prompt = re.sub(r'\bHinglish\b', 'Hindi Devanagari script', system_prompt, flags=re.IGNORECASE)
        system_prompt = re.sub(r'\bhinglish\b', 'Hindi Devanagari script', system_prompt, flags=re.IGNORECASE)
        
        hindi_instruction = (
            "CRITICAL MANDATORY SYSTEM INSTRUCTION (STRICT OVERRIDE):\n"
            "You MUST write your ENTIRE response using HINDI DEVANAGARI SCRIPT ONLY (हिंदी देवनागरी लिपि).\n"
            "DO NOT write in Hinglish or English alphabet! Write all words in Devanagari script (e.g., 'अरे! क्या हाल है? मैं बहुत अच्छी हूँ!').\n"
            "Even slang words must be written in Devanagari script!\n"
            "DO NOT OUTPUT A SINGLE WORD IN ENGLISH/HINGLISH ALPHABET."
        )
        system_prompt = f"{hindi_instruction}\n\n{system_prompt}\n\n{hindi_instruction}"

    chat_history = request.chat_history or []
    
    messages = [{"role": "system", "content": system_prompt}]
    for msg in chat_history[-6:]:
        raw_role = str(msg.get("role", "user")).lower()
        role = "assistant" if raw_role in ["assistant", "agent", "bot"] else "user"
        messages.append({"role": role, "content": msg.get("content", "")})
    messages.append({"role": "user", "content": request.message})
    
    model_name = request.model or agent.get("modelMapping", "llama-3.2-3b")
    
    voice_profile = agent.get("voiceProfile")
    is_female = any(fem in (agent.get("name", "") + " " + agent.get("role", "")).lower() for fem in ["shilpi", "ananya", "swara", "neerja", "female", "woman", "girl", "sarah", "bella"])
    voice_id = voice_profile.get("voiceId") or voice_profile.get("clonedVoiceBase") if voice_profile else ("kokoro-af_bella" if is_female else "kokoro-am_adam")
    sample_path = voice_profile.get("samplePath") if voice_profile else None
    pitch = voice_profile.get("pitch", 1.0) if voice_profile else 1.0
    rate = voice_profile.get("rate", 1.0) if voice_profile else 1.0
    
    llm_service = LocalLLMService()
    
    sse_queue: asyncio.Queue = asyncio.Queue()
    work_queue: asyncio.Queue = asyncio.Queue()
    sentence_counter = 0
    # Single worker on purpose: XTTS serializes every request behind one global
    # GPU lock, so extra workers add no throughput — they only let a later
    # sentence win the lock ahead of an earlier one, delaying the audio the
    # listener is actually waiting for.
    NUM_TTS_WORKERS = 1
    loop = asyncio.get_running_loop()
    
    # Track when all TTS workers have finished
    tts_done_event = asyncio.Event()
    llm_done_text = ""  # Store the full text from LLM DONE event
    
    async def tts_worker(worker_id: int):
        while True:
            item = await work_queue.get()
            if item is None:
                work_queue.task_done()
                break
            text, p_pitch, p_rate, p_sample, p_voice, seq_num = item
            try:
                # The over-generation guard runs on every sentence, including the
                # first. Skipping it there bought ~2s of latency at the cost of
                # the opening line — the one the listener judges the voice by —
                # being the most likely to ramble or mumble.
                audio_bytes, media_type, engine = await VoiceEngineService.generate_speech_audio(
                    text, pitch=p_pitch, rate=p_rate, sample_path=p_sample, voice_base=p_voice, fast_mode=True
                )
                audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
                event_data = f"data: {json.dumps({'type': 'audio_chunk', 'audio': audio_b64, 'text': text, 'media_type': media_type, 'seq': seq_num, 'engine': engine})}\n\n"
                await sse_queue.put(event_data)
                print(f"[StreamTTS] Worker-{worker_id} completed sentence {seq_num} via {engine} ({len(text)} chars -> {len(audio_bytes)} bytes)")
            except Exception as e:
                print(f"[StreamTTS] Worker-{worker_id} error for sentence {seq_num}: {e}")
                err_data = f"data: {json.dumps({'type': 'audio_error', 'message': str(e), 'text': text, 'seq': seq_num})}\n\n"
                await sse_queue.put(err_data)
            finally:
                work_queue.task_done()

    def run_llm_producer_thread():
        nonlocal sentence_counter, llm_done_text
        try:
            for event_type, data in llm_service.stream_chat(messages, model_name):
                if event_type == "TOKEN":
                    payload = f"data: {json.dumps({'type': 'token', 'content': data})}\n\n"
                    loop.call_soon_threadsafe(sse_queue.put_nowait, payload)
                elif event_type == "SENTENCE":
                    seq = sentence_counter
                    sentence_counter += 1
                    loop.call_soon_threadsafe(work_queue.put_nowait, (data, pitch, rate, sample_path, voice_id, seq))
                    payload = f"data: {json.dumps({'type': 'sentence', 'text': data, 'seq': seq})}\n\n"
                    loop.call_soon_threadsafe(sse_queue.put_nowait, payload)
                elif event_type == "DONE":
                    llm_done_text = data
                    # Send stop sentinels to all TTS workers
                    for _ in range(NUM_TTS_WORKERS):
                        loop.call_soon_threadsafe(work_queue.put_nowait, None)
                elif event_type == "ERROR":
                    payload = f"data: {json.dumps({'type': 'error', 'message': data})}\n\n"
                    loop.call_soon_threadsafe(sse_queue.put_nowait, payload)
        except Exception as err:
            print(f"[StreamTTS] LLM producer error: {err}")
            payload = f"data: {json.dumps({'type': 'error', 'message': str(err)})}\n\n"
            loop.call_soon_threadsafe(sse_queue.put_nowait, payload)
            # Still send stop sentinels on error
            for _ in range(NUM_TTS_WORKERS):
                loop.call_soon_threadsafe(work_queue.put_nowait, None)

    async def wait_for_tts_workers(workers):
        """Wait for all TTS workers to finish, then signal completion."""
        await work_queue.join()
        await asyncio.gather(*workers, return_exceptions=True)
        tts_done_event.set()

    async def event_generator():
        workers = [asyncio.create_task(tts_worker(i)) for i in range(NUM_TTS_WORKERS)]
        producer_task = asyncio.create_task(asyncio.to_thread(run_llm_producer_thread))
        waiter_task = asyncio.create_task(wait_for_tts_workers(workers))
        
        try:
            # Keep yielding SSE events until TTS workers are done AND queue is empty
            while True:
                if tts_done_event.is_set() and sse_queue.empty():
                    break
                try:
                    item = await asyncio.wait_for(sse_queue.get(), timeout=0.1)
                    if item is not None:
                        yield item
                except asyncio.TimeoutError:
                    continue
            
            # Send the final 'done' event AFTER all audio has been yielded
            done_payload = f"data: {json.dumps({'type': 'done', 'full_text': llm_done_text})}\n\n"
            yield done_payload
        finally:
            if not producer_task.done():
                producer_task.cancel()
            if not waiter_task.done():
                waiter_task.cancel()

    return StreamingResponse(event_generator(), media_type="text/event-stream")
