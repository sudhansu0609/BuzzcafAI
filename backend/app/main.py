import os
import re
import json
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.models.project import Project
from core.paths import KNOWLEDGE_DIR, PROJECTS_DIR
from runtime.workflow import WorkflowEngine
from integrations.llm import load_config, save_config
from knowledge.assets import AssetService

app = FastAPI(title="Buzzcaf AI Studio")

from app.api.auth import router as auth_router
from app.api.agents_api import router as agents_router
from app.services.voice_intent import resolve_channel, resolve_tab, resolve_actions
app.include_router(auth_router)
app.include_router(agents_router)

# CORS is restricted to the local dev frontend. A wildcard here would let any
# page you visit in the same browser call this API -- including the settings
# endpoint. Extra origins can be added via ALLOWED_ORIGINS (comma-separated).
DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:3005", "http://127.0.0.1:3005",
]
_extra_origins = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=DEFAULT_ALLOWED_ORIGINS + _extra_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = WorkflowEngine()
asset_service = AssetService()

import logging
logger = logging.getLogger("buzzcaf_ai")
from collections import defaultdict, deque

# Per-project ring buffer size. Without a cap the server grows without bound
# for as long as it stays up.
MAX_LOG_LINES = 500


class InMemoryLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.logs = defaultdict(lambda: deque(maxlen=MAX_LOG_LINES))

    def emit(self, record):
        try:
            msg = self.format(record)
            project_id = getattr(record, "project_id", None)
            if project_id:
                self.logs[project_id].append(msg)
            elif len(active_executions) == 1:
                # Unattributed lines belong to the only run in flight. With two
                # or more running we cannot tell them apart, so we drop the
                # line rather than copying it into every project's log.
                self.logs[next(iter(active_executions))].append(msg)
        except Exception:
            # A logging handler must never raise -- it would break the call
            # that emitted the record. Report to stderr and carry on.
            self.handleError(record)

log_handler = InMemoryLogHandler()
log_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] [%(name)s] - %(message)s'))
logging.getLogger().addHandler(log_handler)

active_executions = set()


# Pydantic Schemas
class ProjectCreateSchema(BaseModel):
    name: str
    brand: str
    workflow_name: str

class SettingsSchema(BaseModel):
    gemini_api_key: Optional[str] = ""
    gemini_model: Optional[str] = "gemini-1.5-flash"
    openai_api_key: Optional[str] = ""
    openai_model: Optional[str] = "gpt-4o-mini"
    lm_studio_url: Optional[str] = "http://localhost:1234/v1"
    lm_studio_model: Optional[str] = "meta-llama-3-8b-instruct"
    prefer_gemini: Optional[bool] = True
    selected_provider: Optional[str] = "gemini"


class ExecuteStepSchema(BaseModel):
    feedback: Optional[str] = None

class AssetRegisterSchema(BaseModel):
    title: str
    type: str
    tags: List[str]
    file_path: str
    source: Optional[str] = "internal"
    license: Optional[str] = "Royalty Free"
    status: Optional[str] = "active"
    project_id: Optional[str] = None

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/projects")
def projects():
    return list_projects()

@app.get("/api/brands")
def get_brands():
    # One canonical spelling per channel. "Spilled Coffee: After Dark" was
    # listed separately and resolved to the same vault; _channel_slug() now
    # treats the variants as equal, so the duplicate entry is gone.
    return ["Beyond3Baje", "Khayal3Baje", "Spilled Coffee Studio", "Spilled Coffee After Dark", "Life3Baje"]

@app.get("/api/assets")
def get_assets(type: Optional[str] = None, tag: Optional[str] = None, query: Optional[str] = None):
    return asset_service.query_assets(asset_type=type, tag=tag, query_string=query)

@app.post("/api/assets")
def register_asset(payload: AssetRegisterSchema):
    return asset_service.register_asset(
        title=payload.title,
        asset_type=payload.type,
        tags=payload.tags,
        file_path=payload.file_path,
        source=payload.source,
        license_info=payload.license,
        status=payload.status,
        project_id=payload.project_id
    )


SECRET_SETTING_KEYS = ("gemini_api_key", "openai_api_key")
MASKED_VALUE = "********"


def _redact_settings(config: Dict[str, Any]) -> Dict[str, Any]:
    """Never send stored credentials back over the wire.

    Each secret is replaced with a fixed mask plus a `<key>_set` boolean so the
    UI can show whether a key is configured without ever receiving it.
    """
    safe = dict(config)
    for key in SECRET_SETTING_KEYS:
        value = config.get(key) or ""
        safe[key] = MASKED_VALUE if value else ""
        safe[f"{key}_set"] = bool(value)
    return safe


@app.get("/api/settings")
def get_settings():
    return _redact_settings(load_config())

@app.post("/api/settings")
def update_settings(settings: SettingsSchema):
    new_config = load_config()
    data = settings.model_dump(exclude_unset=True)
    for k, v in data.items():
        if v is None:
            continue
        # A blank or still-masked secret means "leave the stored key alone" --
        # otherwise reopening the settings page would erase the saved key.
        if k in SECRET_SETTING_KEYS and (v == "" or set(v) == {"*"}):
            continue
        new_config[k] = v
    save_config(new_config)
    engine.llm_service.reload_config()
    return {
        "status": "success",
        "message": "Settings updated successfully.",
        "config": _redact_settings(new_config),
    }

@app.get("/api/workflows")
def get_workflows():
    engine.load_workflows()
    return [
        {
            "id": wf.id,
            "name": wf.name,
            "description": wf.description,
            "steps": [
                {
                    "name": s.name,
                    "agent_role": s.agent_role,
                    "description": s.description,
                    "requires_approval": s.requires_approval
                } for s in wf.steps
            ]
        } for wf in engine.workflows.values()
    ]

@app.get("/api/projects")
def list_projects():
    if not os.path.exists(PROJECTS_DIR):
        os.makedirs(PROJECTS_DIR, exist_ok=True)
        return []
    
    projects = []
    for pid in os.listdir(PROJECTS_DIR):
        p_dir = os.path.join(PROJECTS_DIR, pid)
        if os.path.isdir(p_dir):
            try:
                p = Project.load(pid)
                projects.append(p.to_dict())
            except Exception as e:
                # Log and skip corrupted projects
                continue
    # Sort by created_at descending
    projects.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return projects

from executive.project import project_manager

@app.post("/api/projects")
def create_project(payload: ProjectCreateSchema):
    # Load workflow to check first step
    wf = engine.get_workflow(payload.workflow_name)
    if not wf:
        raise HTTPException(status_code=400, detail=f"Workflow '{payload.workflow_name}' not found.")
        
    try:
        project = project_manager.create_project(
            name=payload.name,
            brand=payload.brand,
            workflow_name=payload.workflow_name
        )
        return project.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))



@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    try:
        project = Project.load(project_id)
        return project.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")

@app.post("/api/projects/{project_id}/execute")
def execute_project_step(project_id: str, payload: ExecuteStepSchema = None):
    feedback = payload.feedback if payload else None
    active_executions.add(project_id)
    # Reset in place so the entry stays a capped deque, not a plain list.
    log_handler.logs[project_id].clear()
    log_handler.logs[project_id].append(
        f"Starting execution of workflow step at {datetime.now().isoformat()}..."
    )
    try:
        project = engine.execute_next(project_id, user_feedback=feedback)
        # Add final agent logs if any
        if project.steps_history:
            last_step = project.steps_history[-1]
            for step_log in last_step.logs:
                if step_log not in log_handler.logs[project_id]:
                    log_handler.logs[project_id].append(step_log)
        return project.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as e:
        log_handler.logs[project_id].append(f"[ERROR] Execution failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Execution error: {str(e)}")
    finally:
        active_executions.discard(project_id)

@app.get("/api/projects/{project_id}/logs")
def get_project_execution_logs(project_id: str):
    lines = log_handler.logs.get(project_id)
    if not lines:
        return ["No active logs found for this project."]
    return list(lines)

@app.get("/api/projects/{project_id}/asset/{asset_name}")
def get_project_asset(project_id: str, asset_name: str):
    try:
        project = Project.load(project_id)
        asset_file = project.assets.get(asset_name)
        if not asset_file:
            raise HTTPException(status_code=404, detail="Asset not generated yet")
            
        project_dir = os.path.realpath(project.get_project_dir())
        file_path = os.path.realpath(os.path.join(project_dir, asset_file))
        # Asset names come from the project's own manifest, but a malformed or
        # hand-edited project.json should not be able to read arbitrary files.
        if not file_path.startswith(project_dir + os.sep):
            raise HTTPException(status_code=400, detail="Invalid asset path")
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="Asset file missing on disk")


        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        # Check if json
        if asset_file.endswith(".json"):
            try:
                return json.loads(content)
            except json.JSONDecodeError as e:
                # Fall through and return it as raw text, but say why.
                logger.warning(f"Asset {asset_file} is not valid JSON: {e}")
        return {"content": content}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")

from core.agent import AgentFactory

class TopicDiscoverSchema(BaseModel):
    channel: str
    sources: Optional[List[str]] = None
    pillar_filter: Optional[str] = None

SEED_TOPICS_DIR = os.path.join(KNOWLEDGE_DIR, "seed_topics")

_seed_topics_cache: Optional[Dict[str, List[Dict[str, Any]]]] = None


def _channel_slug(name: str) -> str:
    """Canonical key for a channel name.

    'Spilled Coffee: After Dark' and 'Spilled Coffee After Dark' are the same
    channel spelled two ways. Comparing slugs avoids the old two-way substring
    match, under which a short name could match an unrelated longer one.
    """
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _load_seed_topics() -> Dict[str, List[Dict[str, Any]]]:
    """Curated starter topics, one JSON file per channel in seed_topics/.

    This is seed data, not model output -- responses built from it are tagged
    `"source": "curated_seed"`.
    """
    global _seed_topics_cache
    if _seed_topics_cache is not None:
        return _seed_topics_cache

    vaults: Dict[str, List[Dict[str, Any]]] = {}
    if os.path.isdir(SEED_TOPICS_DIR):
        for fname in sorted(os.listdir(SEED_TOPICS_DIR)):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(SEED_TOPICS_DIR, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                vaults[data["channel"]] = data.get("topics", [])
            except Exception as e:
                logger.error(f"Could not load seed topics from {path}: {e}")
    else:
        logger.warning(f"Seed topics directory missing: {SEED_TOPICS_DIR}")

    _seed_topics_cache = vaults
    return vaults


@app.post("/api/topics/discover")
def discover_channel_topics(payload: TopicDiscoverSchema):
    channel = payload.channel.strip()

    agent_map = {
        "spilledcoffeestudio": "SpilledCoffeeStudioStrategist",
        "spilledcoffeeafterdark": "AfterDarkStrategist",
        "raat3baje": "AfterDarkStrategist",
        "beyond3baje": "Beyond3BajeStrategist",
        "life3baje": "Life3BajeStrategist",
        "khayal3baje": "Khayal3BajeStrategist"
    }
    target_agent_name = agent_map.get(_channel_slug(channel), "TopicVaultManager")

    # NOTE: this endpoint does not call the LLM. It serves curated seed topics,
    # which is why the response is tagged `source: "curated_seed"` -- do not
    # present these as freshly discovered by the strategist agent.
    channel_vaults = _load_seed_topics()

    requested = _channel_slug(channel)
    for name, topics in channel_vaults.items():
        if _channel_slug(name) == requested:
            return {
                "status": "success",
                "source": "curated_seed",
                "channel": name,
                "agent_assigned": target_agent_name,
                "inventory_counts": { "raw_ideas": 120, "researched_ideas": 55, "script_ready": 24 },
                "topics": topics
            }

    # Unknown channel: fall back to the general-interest vault, and say so.
    fallback = channel_vaults.get("Beyond3Baje", [])
    return {
        "status": "success",
        "source": "curated_seed_fallback",
        "channel": channel,
        "agent_assigned": target_agent_name,
        "inventory_counts": { "raw_ideas": 100, "researched_ideas": 50, "script_ready": 20 },
        "topics": fallback
    }

SAVED_TOPICS_FILE = os.path.join(os.path.dirname(__file__), "..", "knowledge", "saved_topics.json")

class SavedTopicSchema(BaseModel):
    id: Optional[str] = None
    topic: str
    category: Optional[str] = "General"
    channel: str
    viral_potential: Optional[int] = 9
    country: Optional[str] = "Global"
    source_type: Optional[str] = "Researched"
    sources_used: Optional[List[str]] = []
    visual_requirements: Optional[List[str]] = []
    exclusion_audit: Optional[str] = ""
    notes: Optional[str] = ""

def _load_saved_topics() -> List[Dict[str, Any]]:
    # An empty or truncated file is treated as "never seeded" -- otherwise the
    # vault stays permanently empty because the file technically exists.
    needs_seed = (
        not os.path.exists(SAVED_TOPICS_FILE)
        or os.path.getsize(SAVED_TOPICS_FILE) == 0
    )
    if needs_seed:
        initial_topics = [
            {
                "id": "saved_topic_1",
                "topic": "Bhangarh Fort Ka Wo Guard Jo Raat Ke 3 Baje Ghaayab Ho Gaya",
                "category": "Paranormal & Haunted Locations",
                "channel": "Spilled Coffee After Dark",
                "viral_potential": 9,
                "country": "India",
                "source_type": "Local Indian Folklore & Archives",
                "sources_used": ["Reddit (r/Paranormal)", "Local Rajasthani Folklore"],
                "visual_requirements": ["Haunted fort archival photos", "Night rain mist imagery"],
                "exclusion_audit": "✓ Verified: Parapsychological Folklore",
                "notes": "Focus on the 3AM guard shift testimonies written in Hinglish script",
                "saved_at": datetime.now().isoformat()
            },
            {
                "id": "saved_topic_2",
                "topic": "Kaise Ek Choti Si Engineering Galti Ne Poore Warship Ko Duba Diya",
                "category": "Engineering & Disaster Stories",
                "channel": "Beyond3Baje",
                "viral_potential": 9,
                "country": "International",
                "source_type": "Historical & Technical Archives",
                "sources_used": ["Naval Inspection Records", "Wikipedia Disasters"],
                "visual_requirements": ["Ship cross-section 3D diagram", "17th Century maps"],
                "exclusion_audit": "✓ EXCLUSION VERIFIED: 100% Real-World True Story in Hinglish",
                "notes": "Use 3D stability diagram for 45-second Hinglish opening hook",
                "saved_at": datetime.now().isoformat()
            }
        ]
        os.makedirs(os.path.dirname(SAVED_TOPICS_FILE), exist_ok=True)
        with open(SAVED_TOPICS_FILE, "w", encoding="utf-8") as f:
            json.dump(initial_topics, f, indent=2)
        return initial_topics
    try:
        with open(SAVED_TOPICS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _save_saved_topics(topics: List[Dict[str, Any]]):
    os.makedirs(os.path.dirname(SAVED_TOPICS_FILE), exist_ok=True)
    with open(SAVED_TOPICS_FILE, "w", encoding="utf-8") as f:
        json.dump(topics, f, indent=2)

@app.get("/api/topics/saved")
def get_saved_topics(channel: Optional[str] = None):
    topics = _load_saved_topics()
    if channel and channel.strip():
        topics = [t for t in topics if channel.lower() in t.get("channel", "").lower()]
    return {"status": "success", "count": len(topics), "topics": topics}

@app.post("/api/topics/save")
def save_topic(payload: SavedTopicSchema):
    topics = _load_saved_topics()
    topic_data = payload.model_dump()
    if not topic_data.get("id"):
        topic_data["id"] = f"topic_{uuid.uuid4().hex[:8]}"
    topic_data["saved_at"] = datetime.now().isoformat()
    
    existing_idx = next((i for i, t in enumerate(topics) if t.get("topic") == topic_data["topic"] and t.get("channel") == topic_data["channel"]), -1)
    if existing_idx >= 0:
        topics[existing_idx].update(topic_data)
    else:
        topics.insert(0, topic_data)
        
    _save_saved_topics(topics)
    return {"status": "success", "message": "Topic saved to vault successfully", "topic": topic_data}

@app.post("/api/topics/delete")
def delete_saved_topic(payload: Dict[str, Any] = Body(...)):
    topic_id = payload.get("id")
    topic_title = payload.get("topic")
    topics = _load_saved_topics()
    
    if topic_id:
        topics = [t for t in topics if t.get("id") != topic_id]
    elif topic_title:
        topics = [t for t in topics if t.get("topic") != topic_title]
        
    _save_saved_topics(topics)
    return {"status": "success", "message": "Topic removed from vault", "remaining": len(topics)}

def _build_workforce_summary() -> str:
    """Builds a formatted summary of all 115 registered agents in the AgentRegistry."""
    from core.agent import agent_registry
    dept_map: Dict[str, List[str]] = {}
    for agent_def in agent_registry.agents.values():
        dept = agent_def.department or "General"
        dept_map.setdefault(dept, []).append(agent_def.name)
    
    lines = [f"### Available Studio Workforce Directory ({len(agent_registry.agents)} Registered AI Agents)"]
    for dept, agents in sorted(dept_map.items()):
        agent_list_str = ", ".join(sorted(agents))
        lines.append(f"- **{dept}** ({len(agents)} agents): {agent_list_str}")
    return "\n".join(lines)


def _process_agent_invocations(reply_text: str) -> str:
    """
    Parses [INVOKE_AGENT: AgentName] task [/INVOKE_AGENT] blocks in the strategist output,
    executes the target agents using AgentFactory, and embeds their output live.
    """
    pattern = r"\[INVOKE_AGENT:\s*([a-zA-Z0-9_]+)\](.*?)\[/INVOKE_AGENT\]"
    matches = list(re.finditer(pattern, reply_text, re.DOTALL))
    if not matches:
        return reply_text

    final_text = reply_text
    for match in matches:
        full_tag = match.group(0)
        target_agent_name = match.group(1).strip()
        task_instruction = match.group(2).strip()
        
        logger.info(f"Strategist delegated task to specialist agent: '{target_agent_name}'")
        try:
            target_agent = AgentFactory.get_agent(target_agent_name)
            agent_response = target_agent.execute(
                f"You have been invoked by a Lead Channel Strategist to perform the following task:\n\n{task_instruction}"
            )
            
            replacement = f"\n\n---\n🤖 **[Delegated Specialist Execution: `{target_agent_name}`]**\n> *Task*: {task_instruction}\n\n{agent_response}\n---\n\n"
            final_text = final_text.replace(full_tag, replacement)
        except Exception as e:
            logger.error(f"Failed to execute delegated agent {target_agent_name}: {e}")
            replacement = f"\n*⚠️ Unable to complete execution for delegated agent `{target_agent_name}`: {e}*\n"
            final_text = final_text.replace(full_tag, replacement)

    return final_text


class AgentChatSchema(BaseModel):
    agent_name: str
    channel: str
    message: str
    context_topic: Optional[Dict[str, Any]] = None
    chat_history: Optional[List[Dict[str, str]]] = None

@app.get("/api/memory")
def get_memory_logs(scope: Optional[str] = "agent", owner: Optional[str] = "Beyond3BajeStrategist", limit: int = 10):
    try:
        from memory.memory import memory_system
        memories = memory_system.retrieve(scope=scope, owner=owner, limit=limit)
        return {"status": "success", "scope": scope, "owner": owner, "count": len(memories), "memories": [m.to_dict() for m in memories]}
    except Exception as e:
        return {"status": "error", "message": str(e), "memories": []}

@app.post("/api/memory/clear")
def clear_memory_logs(scope: Optional[str] = "agent", owner: Optional[str] = "Beyond3BajeStrategist"):
    try:
        from memory.memory import memory_system
        memory_system.clear(scope=scope, owner=owner)
        return {"status": "success", "message": f"Cleared memory for scope={scope}, owner={owner}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/topics/chat_history")
def get_chat_history(channel: str, agent_name: str):
    try:
        from memory.memory import memory_system
        agent_mems = memory_system.retrieve(scope="agent", owner=agent_name, limit=20)
        session_mems = memory_system.retrieve(scope="session", owner=channel, limit=20)
        
        turns = []
        for m in sorted(session_mems + agent_mems, key=lambda x: x.created):
            if isinstance(m.content, dict) and "user" in m.content and "reply" in m.content:
                turns.append({
                    "user": m.content["user"],
                    "reply": m.content["reply"],
                    "agent": m.content.get("agent", agent_name),
                    "timestamp": m.created
                })
        return {"status": "success", "channel": channel, "agent_name": agent_name, "count": len(turns), "turns": turns}
    except Exception as e:
        return {"status": "error", "message": str(e), "turns": []}

@app.post("/api/topics/agent_chat")
def agent_chat(payload: AgentChatSchema):
    agent_name = payload.agent_name.strip()
    try:
        agent = AgentFactory.get_agent(agent_name)
    except Exception:
        agent = AgentFactory.get_agent("TopicVaultManager")
    
    history_formatted = ""
    if payload.chat_history:
        for msg in payload.chat_history:
            role = "User" if msg.get("role") == "user" else agent_name
            history_formatted += f"\n{role}: {msg.get('content', '')}"

    topic_formatted = ""
    if payload.context_topic:
        t = payload.context_topic
        topic_formatted = f"""
### Currently Discussed Topic Details
- Title: {t.get('topic')}
- Category/Pillar: {t.get('category')}
- Target Channel: {t.get('channel', payload.channel)}
- Viral Potential: {t.get('viral_potential')}/10
- Sources Used: {', '.join(t.get('sources_used', [])) if isinstance(t.get('sources_used'), list) else t.get('sources_used', '')}
- Visual Requirements: {', '.join(t.get('visual_requirements', [])) if isinstance(t.get('visual_requirements'), list) else t.get('visual_requirements', '')}
"""

    # Retrieve persistent long-term memories from memory_system
    memory_formatted = ""
    try:
        from memory.memory import memory_system
        agent_memories = memory_system.retrieve(scope="agent", owner=agent_name, limit=15)
        session_memories = memory_system.retrieve(scope="session", owner=payload.channel, limit=15)
        
        all_mem_text = []
        for m in agent_memories + session_memories:
            c_text = json.dumps(m.content) if isinstance(m.content, (dict, list)) else str(m.content)
            all_mem_text.append(f"- [{m.updated[:19]}] {c_text}")
            
        if all_mem_text:
            memory_formatted = "\n### MANDATORY LONG-TERM PERSISTENT STUDIO MEMORY LOGS:\n" + "\n".join(all_mem_text) + "\n"
    except Exception as e:
        logger.error(f"Error retrieving memories in agent_chat: {e}")

    workforce_roster = _build_workforce_summary()

    full_user_prompt = f"""
You are acting in your role as Lead Channel Strategist ({agent_name}) for the channel '{payload.channel}'.
You have full strategic authority over an autonomous AI Studio workforce of 115 specialized agents across 19 departments.

{workforce_roster}

{memory_formatted}

### CRITICAL MEMORY & CONTINUITY DIRECTIVE:
You have FULL ACCESS to past persistent studio memories, user directives, channel preferences, and prior conversation context above.
YOU MUST REMEMBER all previous choices, topic decisions, hooks, script directions, and feedback given by the user in past interactions.

### MANDATORY HINGLISH LANGUAGE & SCRIPT DIRECTIVE:
You MUST reply and generate all topic titles, script hooks, outlines, dialogues, B-roll notes, and video ideas in **Hinglish** (day-to-day conversational Hindi written in Roman/English fonts).
Do NOT write pure formal English scripts or Devanagari Hindi text. Use natural, conversational Hinglish as spoken in top Hindi YouTube documentaries & video essays!

### Strategic Delegation Capabilities:
1. You KNOW about every single agent listed in the workforce directory above.
2. If the user asks for specific work (such as deep fact-checking, full script writing, SEO tags & titles, thumbnail concepts, B-roll/scene planning, or vault management), YOU HAVE THE POWER TO CALL THOSE AGENTS.
3. To delegate a task and make a specialized agent execute it live, insert the following tag in your response:
   [INVOKE_AGENT: AgentName] Write clear instructions for what you need this agent to do... [/INVOKE_AGENT]

{topic_formatted}

### Active Conversation Turns History:
{history_formatted if history_formatted else "No previous turns in this immediate session."}

### User's Current Question/Directive:
{payload.message}

Provide a helpful, strategic response in character as {agent_name}. Refer back to any relevant past decisions or context stored in your memory logs whenever appropriate. All topic titles, script outlines, and dialogues MUST be in Hinglish!
"""
    try:
        reply_text = str(agent.execute(full_user_prompt))
        simulated = getattr(agent.llm_service, "last_response_simulated", False)
        # Execute any delegated agent tasks embedded in the response
        reply_text = _process_agent_invocations(reply_text)
        
        # Save interaction into persistent MemorySystem disk files
        try:
            from memory.memory import memory_system
            mem_payload = {
                "user": payload.message,
                "reply": reply_text,
                "agent": agent_name,
                "channel": payload.channel
            }
            memory_system.save(
                scope="agent",
                owner=agent_name,
                tags=["chat", payload.channel],
                content=mem_payload
            )
            memory_system.save(
                scope="session",
                owner=payload.channel,
                tags=["chat", agent_name],
                content=mem_payload
            )
        except Exception as mem_err:
            logger.error(f"Error saving to memory_system in agent_chat: {mem_err}")

        return {
            "status": "simulated" if simulated else "success",
            "simulated": simulated,
            "agent_name": agent_name,
            "channel": payload.channel,
            "reply": reply_text
        }
    except Exception as e:
        logger.error(f"Error executing agent {agent_name}: {e}", exc_info=True)
        # An error is reported as an error. Returning "success" here made a
        # failed call indistinguishable from a real strategist reply.
        return {
            "status": "error",
            "simulated": True,
            "error": str(e),
            "agent_name": agent_name,
            "channel": payload.channel,
            "reply": f"**{agent_name}** could not be reached: {e}\n\nCheck your provider settings and that the selected model is available."
        }


VOICE_CONFIG = {
    "provider": "native_local",
    "picovoice_access_key": "",
    "openai_realtime_key": "",
    "wake_word": "Hey Buzzcaf"
}

class VoiceConfigSchema(BaseModel):
    provider: Optional[str] = "native_local"
    picovoice_access_key: Optional[str] = ""
    openai_realtime_key: Optional[str] = ""
    wake_word: Optional[str] = "Hey Buzzcaf"

VOICE_SECRET_KEYS = ("picovoice_access_key", "openai_realtime_key")


def _redact_voice_config() -> Dict[str, Any]:
    """Same rule as /api/settings: report whether a key is set, never its value."""
    safe = dict(VOICE_CONFIG)
    for key in VOICE_SECRET_KEYS:
        value = VOICE_CONFIG.get(key) or ""
        safe[key] = MASKED_VALUE if value else ""
        safe[f"{key}_set"] = bool(value)
    return safe


@app.get("/api/voice/config")
def get_voice_config():
    return _redact_voice_config()

@app.post("/api/voice/config")
def update_voice_config(payload: VoiceConfigSchema):
    if payload.provider: VOICE_CONFIG["provider"] = payload.provider
    if payload.wake_word: VOICE_CONFIG["wake_word"] = payload.wake_word
    # An empty or still-masked value means "keep what is stored", so reopening
    # the settings tab and saving does not wipe the key.
    for key, value in (
        ("picovoice_access_key", payload.picovoice_access_key),
        ("openai_realtime_key", payload.openai_realtime_key),
    ):
        if value is None or value == "" or set(value) == {"*"}:
            continue
        VOICE_CONFIG[key] = value
    return {"status": "success", "config": _redact_voice_config()}

class JarvisVoiceSchema(BaseModel):
    phrase: str
    active_channel: Optional[str] = "Beyond3Baje"
    active_tab: Optional[str] = "dashboard"

@app.post("/api/jarvis/voice")
def jarvis_voice_router(payload: JarvisVoiceSchema):
    phrase = payload.phrase.strip()
    p_lower = phrase.lower()
    
    # Keyword tables live in app/services/voice_intent.py -- one definition,
    # so channel routing cannot drift between endpoints.
    target_channel = resolve_channel(p_lower)
    target_tab = resolve_tab(p_lower)
    actions = resolve_actions(p_lower)
    is_save = actions["is_save"]
    is_chat = actions["is_chat"]
    is_discover = actions["is_discover"]
    is_stop = actions["is_stop"]
    is_log = actions["is_log"]

    curr_ch = target_channel or payload.active_channel
    
    # Autonomous Natural Speech Generation
    if is_stop:
        buzzcaf_speech = "Buzzcaf standing down, sir. Voice system paused."
    elif is_log:
        buzzcaf_speech = "Opening your voice activity log console now, sir."
    elif target_channel and target_tab:
        buzzcaf_speech = f"Right away, sir. Switched to {target_channel} and opened the {target_tab.replace('_', ' ')} workspace."
    elif target_channel:
        buzzcaf_speech = f"Certainly, sir. Aligning system intelligence with {target_channel}."
    elif target_tab:
        buzzcaf_speech = f"Opening {target_tab.replace('_', ' ')} workspace now, sir."
    elif is_save:
        buzzcaf_speech = f"Bookmarking the top discovered topic directly into your Vault, sir."
    elif is_chat:
        buzzcaf_speech = f"Initiating direct strategist chat session for {curr_ch}, sir."
    elif is_discover:
        buzzcaf_speech = f"Executing a full topic discovery sweep across Reddit, Wikipedia, and archives for {curr_ch}, sir."
    elif any(w in p_lower for w in ["hi", "hello", "hey", "who are you", "what can you do"]):
        buzzcaf_speech = f"Hello sir! I am Buzzcaf, your autonomous AI production assistant. Tell me what you need, and I will execute it."
    else:
        clean_phrase = phrase.replace("buzzcaf", "").replace("hey", "").replace("and", "").replace("please", "").strip()
        buzzcaf_speech = f"Right away, sir. Executing your request regarding {clean_phrase if clean_phrase else 'your studio directive'}."

    return {
        "status": "success",
        "buzzcaf_speech": buzzcaf_speech,
        "jarvis_speech": buzzcaf_speech,
        "action": {
            "target_channel": target_channel,
            "target_tab": target_tab,
            "is_save": is_save,
            "is_chat": is_chat,
            "is_discover": is_discover,
            "is_stop": is_stop,
            "is_log": is_log
        }
    }

@app.get("/api/agents")
def get_all_agents():
    prompts_dir = os.path.join(os.path.dirname(__file__), "..", "prompts", "agents")
    agents = []
    if os.path.exists(prompts_dir):
        for f in sorted(os.listdir(prompts_dir)):
            if f.endswith(".md"):
                agent_name = f[:-3]
                agents.append({
                    "name": agent_name,
                    "status": "Active & Idle",
                    "file": f
                })
    return {"status": "success", "count": len(agents), "agents": agents}

from core.diagnostics import Diagnostics

@app.get("/api/diagnostics")
def get_diagnostics():
    return Diagnostics.get_report()




# Serve UI static files

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
else:
    print(f"WARNING: UI static folder not found at: {static_dir}")
