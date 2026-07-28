# Buzzcaf AI - Agents Workbench & Group Chat API Router
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, File, UploadFile, Form, Body
from pydantic import BaseModel

from app.services.agents_registry import agents_registry
from app.services.local_llm import local_llm_service
from app.services.voice_engine import voice_engine_service

router = APIRouter(prefix="/api/agents-workbench", tags=["Agents Workbench"])

class AgentSchema(BaseModel):
    id: Optional[str] = None
    name: str
    role: str
    avatarColor: str = "#7c3aed"
    systemPrompt: str
    modelProvider: str = "LM Studio (http://localhost:1234)"
    modelName: str = "qwen2.5-coder-7b-instruct"
    temperature: float = 0.7
    voiceId: str = "default-voice"

class ChatMessageSchema(BaseModel):
    sender: str
    text: str

class GroupChatRequestSchema(BaseModel):
    agentIds: List[str]
    userMessage: str
    conversationHistory: Optional[List[ChatMessageSchema]] = []
    localModel: Optional[str] = "qwen2.5-coder-7b-instruct"
    providerEndpoint: Optional[str] = "http://localhost:1234/v1"

@router.get("/agents")
def list_all_agents():
    return {"agents": agents_registry.list_agents()}

@router.post("/agents")
def create_or_update_agent(agent_data: AgentSchema):
    saved = agents_registry.save_agent(agent_data.dict())
    return {"status": "success", "agent": saved}

@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: str):
    success = agents_registry.delete_agent(agent_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot delete preset or non-existent agent")
    return {"status": "success", "deleted_id": agent_id}

@router.get("/local-models")
def get_local_models():
    return local_llm_service.detect_local_models()

@router.post("/voice/clone")
async def clone_voice_profile(
    name: str = Form(...),
    file: UploadFile = File(...)
):
    contents = await file.read()
    profile = voice_engine_service.process_voice_cloning_sample(
        voice_name=name,
        sample_audio_bytes=contents,
        filename=file.filename or "sample.wav"
    )
    return {"status": "success", "profile": profile}

@router.get("/voice/profiles")
def list_voice_profiles():
    return voice_engine_service.list_voice_profiles()

@router.post("/chat/group-chat")
def execute_group_chat(req: GroupChatRequestSchema):
    agents = []
    for aid in req.agentIds:
        a = agents_registry.get_agent(aid)
        if a:
            agents.append(a)

    if not agents:
        raise HTTPException(status_code=404, detail="No valid agents selected")

    responses = []
    for agent in agents:
        prompt = agent.get("systemPrompt", "You are an AI assistant.")
        hist = [{"role": m.sender, "content": m.text} for m in req.conversationHistory] + [{"role": "user", "content": req.userMessage}]
        
        result = local_llm_service.generate_agent_chat_response(
            system_prompt=prompt,
            messages=hist,
            model_name=agent.get("modelName", req.localModel),
            provider_endpoint=req.providerEndpoint,
            temperature=agent.get("temperature", 0.7)
        )

        tts_result = voice_engine_service.synthesize_cloned_speech(
            text=result.get("content", ""),
            voice_id=agent.get("voiceId", "default-voice"),
            agent_name=agent.get("name", "Agent")
        )

        responses.append({
            "agentId": agent.get("id"),
            "agentName": agent.get("name"),
            "agentRole": agent.get("role"),
            "avatarColor": agent.get("avatarColor"),
            "response": result.get("content"),
            "modelUsed": result.get("model_used"),
            "voiceAudio": tts_result
        })

    return {
        "status": "success",
        "userMessage": req.userMessage,
        "agentResponses": responses
    }
