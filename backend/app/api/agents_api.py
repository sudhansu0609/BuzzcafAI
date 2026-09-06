# Buzzcaf AI - Agents Workbench & Group Chat API Router
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.agents_registry import agents_registry
from app.services.local_llm import local_llm_service

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
    saved = agents_registry.save_agent(agent_data.model_dump())
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

@router.post("/chat/group-chat")
def execute_group_chat(req: GroupChatRequestSchema):
    agents = []
    for aid in req.agentIds:
        a = agents_registry.get_agent(aid)
        if a:
            agents.append(a)

    if not agents:
        raise HTTPException(status_code=404, detail="No valid agents selected")

    hist = [{"role": m.sender, "content": m.text} for m in req.conversationHistory] + [
        {"role": "user", "content": req.userMessage}
    ]

    def _ask(agent: Dict[str, Any]) -> Dict[str, Any]:
        result = local_llm_service.generate_agent_chat_response(
            system_prompt=agent.get("systemPrompt", "You are an AI assistant."),
            messages=list(hist),
            model_name=agent.get("modelName", req.localModel),
            provider_endpoint=req.providerEndpoint,
            temperature=agent.get("temperature", 0.7)
        )

        return {
            "agentId": agent.get("id"),
            "agentName": agent.get("name"),
            "agentRole": agent.get("role"),
            "avatarColor": agent.get("avatarColor"),
            "response": result.get("content"),
            "modelUsed": result.get("model_used"),
            # The model server was unreachable and this text is canned. The UI
            # must label it -- otherwise a fallback reads as a real answer.
            "simulated": result.get("status") != "success",
        }

    # Each agent is an independent ~30s network call. Run them concurrently so
    # a five-agent room answers in one round trip instead of five.
    with ThreadPoolExecutor(max_workers=min(len(agents), 8)) as pool:
        responses = list(pool.map(_ask, agents))

    any_simulated = any(r["simulated"] for r in responses)
    return {
        "status": "simulated" if any_simulated else "success",
        "simulated": any_simulated,
        "userMessage": req.userMessage,
        "agentResponses": responses
    }
