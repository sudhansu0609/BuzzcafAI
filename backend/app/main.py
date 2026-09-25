import os
import re
import json
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Body, Query
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
import html
import webbrowser
from pydantic import BaseModel

from core.models.project import Project
from core.paths import KNOWLEDGE_DIR, PROJECTS_DIR
from runtime.workflow import WorkflowEngine
from integrations.llm import load_config, save_config
from knowledge.assets import AssetService

app = FastAPI(title="Buzzcaf AI Studio")

from app.api.agents_api import router as agents_router
from app.api.studio_api import router as studio_router
from app.api.buzzbrain_api import router as buzzbrain_router
from app.api.video_intel_api import router as video_intel_router
from app.api.departments_api import router as departments_router
from app.api.produce_api import router as produce_router
from app.services.events import bus as event_bus
app.include_router(agents_router)
app.include_router(studio_router)
app.include_router(buzzbrain_router)
app.include_router(video_intel_router)
app.include_router(departments_router)
app.include_router(produce_router)


@app.on_event("startup")
async def _bind_event_bus():
    # Workflow steps run in the threadpool; the bus needs the loop to publish from there.
    import asyncio

    event_bus.bind_loop(asyncio.get_running_loop())


#: Set by `serve_headless()` when this process published its own ledger entry.
#: The desktop launcher owns the entry in the packaged app, and one process must
#: never withdraw another's.
_owns_ledger_entry = False


def _withdraw_ledger_entry() -> None:
    """Take `buzzcaf` back out of the shared port ledger, at most once."""
    global _owns_ledger_entry
    if not _owns_ledger_entry:
        return
    _owns_ledger_entry = False
    try:
        from integrations import buzzcaf_ports

        buzzcaf_ports.withdraw(APP_ID)
    except Exception as exc:  # a stale entry is bad; a crash on the way out is worse
        print(f"[buzzcaf] could not withdraw from the port ledger: {exc}", flush=True)


@app.on_event("shutdown")
async def _leave_the_port_ledger():
    """Withdraw here, not only in the `finally` around `uvicorn.run`.

    On Windows a console control event - Ctrl+Break, closing the console window,
    the machine shutting down - ends the process from the CRT's default handler
    as soon as uvicorn's own handler returns, so neither `atexit` nor that
    `finally` ever runs and the entry outlives the Studio. This hook is part of
    uvicorn's *application shutdown*, which happens before that. Found in the P4
    integration run: a graceful stop left `buzzcaf -> 8099` in the ledger naming
    a pid that no longer existed.
    """
    _withdraw_ledger_entry()

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
    allow_all: Optional[bool] = False
    # Target video runtime in minutes; the Script/Outline steps write to this
    # length. Optional -- omitted means "no target, write to natural length".
    target_duration_minutes: Optional[float] = None

class SettingsSchema(BaseModel):
    gemini_api_key: Optional[str] = ""
    gemini_model: Optional[str] = "gemini-1.5-flash"
    openai_api_key: Optional[str] = ""
    openai_model: Optional[str] = "gpt-4o-mini"
    lm_studio_url: Optional[str] = "http://localhost:1234/v1"
    lm_studio_model: Optional[str] = "qwen3.8-flash-next"
    ollama_url: Optional[str] = "http://localhost:11434/v1"
    ollama_model: Optional[str] = "qwen3.5:9b"
    llamacpp_url: Optional[str] = "http://127.0.0.1:8089/v1"
    llamacpp_model: Optional[str] = "qwen3.8-27b"
    # Which provider and model each persona tier runs on (roadmap v9, F1):
    # {"fast": {"provider": "llamacpp", "model": ""}, "strong": {...}}
    tiers: Optional[Dict[str, Dict[str, str]]] = None
    local_only: Optional[bool] = True
    prefer_gemini: Optional[bool] = False
    selected_provider: Optional[str] = "lm_studio"
    # YouTube channel ids the owner runs; BuzzBrain snapshots from these are "mine".
    owner_channel_ids: Optional[List[str]] = None
    web_research_enabled: Optional[bool] = True
    search_provider: Optional[str] = "auto"
    searxng_url: Optional[str] = "http://localhost:8080"
    allow_all_steps: Optional[bool] = False


class ExecuteStepSchema(BaseModel):
    feedback: Optional[str] = None
    allow_all: Optional[bool] = None

class AssetRegisterSchema(BaseModel):
    title: str
    type: str
    tags: List[str]
    file_path: str
    source: Optional[str] = "internal"
    license: Optional[str] = "Royalty Free"
    status: Optional[str] = "active"
    project_id: Optional[str] = None

STUDIO_VERSION = "0.5.0"

#: This app's name in the shared port ledger and in every /health body.
APP_ID = "buzzcaf"
#: A wish, not a fact (GUARDIAN_PLAN section 11 rule 1). The launcher may have to
#: step past it, and whoever binds calls set_bound_port() with what it got.
PREFERRED_PORT = int(os.getenv("BUZZCAF_PORT", "8099"))
_bound_port = PREFERRED_PORT


def set_bound_port(port: int) -> None:
    """Record the port uvicorn actually bound, so /health can report the truth."""
    global _bound_port
    _bound_port = int(port)


import threading

_bg_model_loading_lock = threading.Lock()
_bg_model_is_loading = False


def bound_port() -> int:
    return _bound_port


@app.get("/health")
def health(blocking: bool = False):
    # `app` lets Dexter, BuzzBrain and a second launcher confirm they are
    # talking to the Studio and not to some other process on the same port.
    # `port`/`pid` make the answer self-describing, so a scanner that finds us
    # on a stepped-forward port knows where we really are and who we are.
    import requests
    from integrations.llm import models_match, ensure_local_model_loaded, get_loaded_lm_studio_models, is_model_already_loaded
    from core.logger import logger

    config = load_config()
    selected_p = (config.get("selected_provider") or "lm_studio").lower()
    model_name = config.get(f"{selected_p}_model", "")

    model_status: Dict[str, Any] = {
        "provider": selected_p,
        "configured_model": model_name,
        "connected": False,
        "loaded": False,
        "loaded_models": [],
        "active_model": model_name,
    }

    if selected_p == "lm_studio":
        try:
            lm_url = (config.get("lm_studio_url") or "http://localhost:1234/v1").replace("/v1", "")
            loaded = get_loaded_lm_studio_models(lm_url)
            model_status["connected"] = True
            model_status["loaded_models"] = loaded
            is_loaded, matched_mid = is_model_already_loaded(model_name, loaded)
            if is_loaded and matched_mid:
                model_status["loaded"] = True
                model_status["active_model"] = matched_mid
            elif loaded:
                model_status["loaded"] = True
                model_status["active_model"] = loaded[0]
            elif blocking:
                res = ensure_local_model_loaded("lm_studio", model_name)
                if res.get("loaded"):
                    model_status["loaded"] = True
                    model_status["active_model"] = res.get("model")
            else:
                # Non-blocking auto-load in background thread so /health answers in <50ms,
                # ensuring desktop_app.py and ecosystem probes never time out.
                def _bg_load():
                    global _bg_model_is_loading
                    try:
                        logger.info(f"Health check triggering background load for model '{model_name}'...")
                        ensure_local_model_loaded("lm_studio", model_name)
                    except Exception as exc:
                        logger.warning(f"Background load for model '{model_name}' failed: {exc}")
                    finally:
                        _bg_model_is_loading = False

                with _bg_model_loading_lock:
                    global _bg_model_is_loading
                    if not _bg_model_is_loading:
                        _bg_model_is_loading = True
                        threading.Thread(target=_bg_load, name="bg-model-loader", daemon=True).start()

                model_status["loaded"] = False
                model_status["loading"] = True
        except Exception:
            model_status["connected"] = False
    elif selected_p == "ollama":
        try:
            ol_url = (config.get("ollama_url") or "http://localhost:11434/v1").replace("/v1", "")
            r = requests.get(f"{ol_url}/api/tags", timeout=1.0)
            if r.status_code == 200:
                model_status["connected"] = True
                model_status["loaded"] = True
                model_status["active_model"] = model_name
        except Exception:
            model_status["connected"] = False
    elif selected_p == "llamacpp":
        try:
            lc_url = config.get("llamacpp_url") or "http://127.0.0.1:8089/v1"
            r = requests.get(f"{lc_url}/models", timeout=1.0)
            if r.status_code == 200:
                model_status["connected"] = True
                model_status["loaded"] = True
                model_status["active_model"] = model_name
        except Exception:
            model_status["connected"] = False
    elif selected_p in ("gemini", "openai"):
        key_name = f"{selected_p}_api_key"
        has_key = bool(config.get(key_name) or os.environ.get(key_name.upper()))
        model_status["connected"] = has_key
        model_status["loaded"] = has_key
        model_status["active_model"] = model_name

    return {
        "status": "ok",
        "app": APP_ID,
        "version": STUDIO_VERSION,
        "port": _bound_port,
        "pid": os.getpid(),
        "model_status": model_status,
    }

@app.get("/projects")
def projects():
    return list_projects()

@app.get("/api/brands")
def get_brands():
    # One canonical spelling per channel, so the frontend and every stored
    # topic can be compared by slug without variant confusion.
    return ["Beyond3Baje", "Khayal3Baje", "Originals", "Raat3Baje", "Life3Baje"]

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

@app.post("/api/settings/reset")
def reset_settings():
    """Reset settings to clean factory defaults with auto-detected local model."""
    import requests
    from integrations.llm import DEFAULT_TIERS

    detected_model = "qwen3.8-27b-gsq-rco"
    try:
        r = requests.get("http://localhost:1234/api/v0/models", timeout=1.0)
        if r.status_code == 200:
            for m in r.json().get("data", []):
                if m.get("state") == "loaded":
                    detected_model = m.get("id")
                    break
    except Exception:
        pass

    default_config = {
        "gemini_api_key": "",
        "gemini_model": "gemini-1.5-flash",
        "openai_api_key": "",
        "openai_model": "gpt-4o-mini",
        "lm_studio_url": "http://localhost:1234/v1",
        "lm_studio_model": detected_model,
        "ollama_url": "http://localhost:11434/v1",
        "ollama_model": "qwen3.5:9b",
        "llamacpp_url": "http://127.0.0.1:8089/v1",
        "llamacpp_model": "qwen3.8-27b",
        "tiers": {
            "fast": {"provider": "lm_studio", "model": detected_model},
            "strong": {"provider": "lm_studio", "model": detected_model},
        },
        "local_only": True,
        "prefer_gemini": False,
        "selected_provider": "lm_studio",
        "web_research_enabled": True,
        "search_provider": "duckduckgo",
        "allow_all_steps": False,
        "owner_channel_ids": ["@beyond3baje", "@khayal3baje", "@raat3baje"],
        "searxng_url": "http://localhost:8080"
    }
    save_config(default_config)
    engine.llm_service.reload_config()
    return {
        "status": "success",
        "message": "Settings reset to factory defaults successfully.",
        "config": _redact_settings(default_config),
    }

@app.get("/api/settings/local-models")
def get_local_models():
    """Probe active local servers and scan disk for downloaded models in LM Studio, Ollama, and llama.cpp."""
    import requests
    config = load_config()
    detected: Dict[str, List[str]] = {
        "lm_studio": [],
        "ollama": [],
        "llamacpp": []
    }

    # 1. LM Studio (API + Disk)
    lms_set = set()
    lm_url = (config.get("lm_studio_url") or "http://localhost:1234/v1").rstrip("/")
    try:
        r = requests.get(f"{lm_url}/models", timeout=2)
        if r.status_code == 200:
            for m in r.json().get("data", []):
                mid = m.get("id")
                if mid:
                    lms_set.add(mid)
    except Exception:
        pass

    # Disk scan for downloaded LM Studio models
    for lms_dir in [os.path.expanduser("~/.lmstudio/models"), os.path.expanduser("~/.cache/lm-studio/models")]:
        if os.path.isdir(lms_dir):
            try:
                for pub in os.listdir(lms_dir):
                    pub_dir = os.path.join(lms_dir, pub)
                    if os.path.isdir(pub_dir) and pub not in ("blobs", "manifests"):
                        for m in os.listdir(pub_dir):
                            if os.path.isdir(os.path.join(pub_dir, m)):
                                lms_set.add(f"{pub}/{m}")
            except Exception:
                pass
    detected["lm_studio"] = sorted(list(lms_set), key=lambda x: x.lower())

    # 2. Ollama (API + Disk)
    ollama_set = set()
    ollama_base = (config.get("ollama_url") or "http://localhost:11434/v1").rstrip("/")
    try:
        host = ollama_base.replace("/v1", "")
        r = requests.get(f"{host}/api/tags", timeout=2)
        if r.status_code == 200:
            for m in r.json().get("models", []):
                mname = m.get("name") or m.get("model")
                if mname:
                    ollama_set.add(mname)
    except Exception:
        pass

    try:
        r2 = requests.get(f"{ollama_base}/models", timeout=2)
        if r2.status_code == 200:
            for m in r2.json().get("data", []):
                mid = m.get("id")
                if mid:
                    ollama_set.add(mid)
    except Exception:
        pass

    # Disk scan for downloaded Ollama models
    ollama_manifests = os.path.expanduser("~/.ollama/models/manifests")
    if os.path.isdir(ollama_manifests):
        try:
            for root, dirs, files in os.walk(ollama_manifests):
                for f in files:
                    rel = os.path.relpath(os.path.join(root, f), ollama_manifests).replace("\\", "/")
                    parts = rel.split("/")
                    if len(parts) >= 2:
                        tag = parts[-1]
                        model_name = parts[-2]
                        ollama_set.add(f"{model_name}:{tag}" if tag != "latest" else model_name)
        except Exception:
            pass
    detected["ollama"] = sorted(list(ollama_set), key=lambda x: x.lower())

    # 3. llama.cpp
    ll_set = set()
    ll_url = (config.get("llamacpp_url") or "http://127.0.0.1:8089/v1").rstrip("/")
    try:
        r = requests.get(f"{ll_url}/models", timeout=2)
        if r.status_code == 200:
            for m in r.json().get("data", []):
                mid = m.get("id")
                if mid:
                    ll_set.add(mid)
    except Exception:
        pass
    default_ll = config.get("llamacpp_model") or "qwen3.8-27b"
    if default_ll:
        ll_set.add(default_ll)
    detected["llamacpp"] = sorted(list(ll_set), key=lambda x: x.lower())

    return detected

@app.get("/api/research/search")
def run_research_search(q: str = Query(..., description="Query to search"), limit: int = 5):
    """Execute a privacy-safe web search via SearXNG, Wikipedia, and DuckDuckGo."""
    from app.services.web_research import web_research_service
    results = web_research_service.search(q, max_results=limit)
    return {"query": q, "results": results, "count": len(results)}

@app.get("/api/research/fetch")
def run_research_fetch(url: str = Query(..., description="URL to fetch")):
    """Safely fetch clean text from a public web page without scripts or tracking."""
    from app.services.web_research import web_research_service
    content = web_research_service.fetch(url)
    return {"url": url, "content": content}

@app.get("/api/research/sources")
def run_source_research(q: str = Query(...), kinds: str = "news,archives,books", limit: int = 5):
    """Search keyless book/archive/news providers (Gutenberg, Open Library, Internet Archive,
    Wikisource, GDELT, Google News, Chronicling America) and return grouped, deduped results."""
    from app.services.deep_research import deep_research
    kl = tuple(k.strip() for k in kinds.split(",") if k.strip()) or ("news", "archives", "books")
    return deep_research(q, kinds=kl, per_source=limit)

@app.get("/api/research/searxng-test")
def test_searxng_connection(url: Optional[str] = None):
    """Test connection to a SearXNG instance and return status & sample result."""
    from app.services.web_research import search_searxng
    from integrations.llm import load_config
    target_url = (url or load_config().get("searxng_url") or "http://localhost:8080").strip()
    try:
        results = search_searxng("test query", base_url=target_url, max_results=1)
        if results:
            return {
                "status": "ok",
                "message": f"Successfully connected to SearXNG at {target_url}!",
                "url": target_url,
                "sample": results[0]
            }
        else:
            import requests
            r = requests.get(f"{target_url.rstrip('/')}/search", params={"q": "test", "format": "json"}, timeout=3)
            if r.status_code == 200:
                return {
                    "status": "warning",
                    "message": f"SearXNG responded at {target_url}, but returned 0 results for the test query.",
                    "url": target_url
                }
            elif r.status_code == 403 or "json" not in r.headers.get("content-type", ""):
                return {
                    "status": "error",
                    "message": f"SearXNG reachable at {target_url}, but JSON format is disabled in settings.yml (add 'json' to search.formats).",
                    "url": target_url
                }
            else:
                return {
                    "status": "error",
                    "message": f"SearXNG returned HTTP {r.status_code} at {target_url}.",
                    "url": target_url
                }
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Could not reach SearXNG at {target_url}: {exc}",
            "url": target_url
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
                logger.warning(f"Could not load project '{pid}': {e}", exc_info=True)
                continue
    # Sort by created_at descending
    projects.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return projects

from executive.project import project_manager


def _clamp_minutes(value: Optional[float]) -> Optional[float]:
    """A sane target runtime in minutes, or None to clear it (<=0 or unparseable)."""
    try:
        minutes = float(value)
    except (TypeError, ValueError):
        return None
    if minutes <= 0:
        return None
    return round(max(0.5, min(180.0, minutes)), 2)


class DurationSchema(BaseModel):
    minutes: Optional[float] = None


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
        dirty = False
        if payload.allow_all:
            project.metadata["allow_all"] = True
            dirty = True
        minutes = _clamp_minutes(payload.target_duration_minutes)
        if minutes:
            project.metadata["target_duration_minutes"] = minutes
            dirty = True
        if dirty:
            project.save()
        data = project.to_dict()
        event_bus.publish("project_created", {
            "project_id": data.get("id"), "name": data.get("name"), "brand": data.get("brand"),
            "workflow_name": data.get("workflow_name"), "current_step": data.get("current_step"),
        })
        return data
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/projects/{project_id}/duration")
def set_project_duration(project_id: str, payload: DurationSchema):
    """Set (or clear) the project's target video runtime in minutes.

    The Script/Outline steps read this and write to the target length, so the
    creator resizes a video by changing this and re-running the Script step.
    A null/0 value clears the target.
    """
    try:
        project = Project.load(project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")

    minutes = _clamp_minutes(payload.minutes)
    if minutes:
        project.metadata["target_duration_minutes"] = minutes
    else:
        project.metadata.pop("target_duration_minutes", None)
    project.save()
    return project.to_dict()


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    try:
        project = Project.load(project_id)
        return project.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str):
    if project_id in active_executions:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete project '{project_id}' while a step is actively executing.",
        )
    name = project_id
    brand = "Unknown"
    try:
        project = Project.load(project_id)
        name = project.name
        brand = project.brand
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.warning(f"Could not read metadata before deleting project '{project_id}': {e}")

    try:
        project_manager.delete_project(project_id)
        if project_id in log_handler.logs:
            del log_handler.logs[project_id]
        event_bus.publish("project_deleted", {
            "project_id": project_id,
            "name": name,
            "brand": brand,
        })
        return {"status": "deleted", "id": project_id, "name": name}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting project '{project_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete project: {e}")

def _step_event_payload(project_id: str, project) -> Dict[str, Any]:
    last = project.steps_history[-1] if project.steps_history else None
    return {
        "project_id": project_id,
        "name": project.name,
        "brand": project.brand,
        "status": project.status,
        "current_step": project.current_step,
        "step": last.step_name if last else None,
        "step_status": last.status if last else None,
        "agent": last.agent_name if last else None,
    }


@app.post("/api/projects/{project_id}/execute")
def execute_project_step(project_id: str, payload: ExecuteStepSchema = None):
    feedback = payload.feedback if payload else None
    allow_all = payload.allow_all if payload else None
    active_executions.add(project_id)
    # Reset in place so the entry stays a capped deque, not a plain list.
    log_handler.logs[project_id].clear()
    log_handler.logs[project_id].append(
        f"Starting execution of workflow step at {datetime.now().isoformat()}..."
    )
    event_bus.publish("step_started", {"project_id": project_id, "feedback": bool(feedback), "allow_all": bool(allow_all)})
    try:
        project = engine.execute_next(project_id, user_feedback=feedback, allow_all=allow_all)
        # Add final agent logs if any
        if project.steps_history:
            last_step = project.steps_history[-1]
            for step_log in last_step.logs:
                if step_log not in log_handler.logs[project_id]:
                    log_handler.logs[project_id].append(step_log)
        payload_out = _step_event_payload(project_id, project)
        if payload_out.get("step_status") == "paused_for_approval":
            event_bus.publish("approval_needed", payload_out)
        else:
            event_bus.publish("step_completed", payload_out)
        return project.to_dict()
    except ValueError as e:
        event_bus.publish("step_failed", {"project_id": project_id, "error": str(e)})
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as e:
        log_handler.logs[project_id].append(f"[ERROR] Execution failed: {str(e)}")
        event_bus.publish("step_failed", {"project_id": project_id, "error": str(e)})
        raise HTTPException(status_code=500, detail=f"Execution error: {str(e)}")
    finally:
        active_executions.discard(project_id)


@app.post("/api/projects/{project_id}/approve")
def approve_project_step(project_id: str, payload: ExecuteStepSchema = None):
    """
    Approve the step waiting on the creator (or send it back with notes).

    An alias of execute: WorkflowEngine treats "execute with no feedback" on a
    paused step as approval and "execute with feedback" as a revision request.
    Spelling that out as /approve makes Dexter's intent explicit and lets the
    Studio refuse when nothing is actually waiting.
    """
    try:
        project = Project.load(project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    last = project.steps_history[-1] if project.steps_history else None
    if not last or last.status != "paused_for_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Nothing is waiting for approval on '{project.name}' (current step: {project.current_step}).",
        )
    return execute_project_step(project_id, payload)


@app.post("/api/projects/{project_id}/allow_all")
def allow_all_and_advance(project_id: str):
    """Enable Allow All mode on this project and unblock any waiting step."""
    try:
        project = Project.load(project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")

    project.metadata["allow_all"] = True
    project.save()

    last = project.steps_history[-1] if project.steps_history else None
    if last and last.status == "paused_for_approval":
        return execute_project_step(project_id, ExecuteStepSchema(allow_all=True))
    return project.to_dict()


@app.post("/api/projects/{project_id}/toggle_allow_all")
def toggle_project_allow_all(project_id: str):
    """Toggle Allow All mode on this project."""
    try:
        project = Project.load(project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")

    current = bool(project.metadata.get("allow_all"))
    project.metadata["allow_all"] = not current
    project.save()

    if project.metadata["allow_all"]:
        last = project.steps_history[-1] if project.steps_history else None
        if last and last.status == "paused_for_approval":
            return execute_project_step(project_id, ExecuteStepSchema(allow_all=True))

    return project.to_dict()


@app.post("/api/projects/{project_id}/run_all")
def run_all_project_steps(project_id: str):
    """Run all remaining steps of the project continuously until completion."""
    active_executions.add(project_id)
    log_handler.logs[project_id].clear()
    log_handler.logs[project_id].append(
        f"Starting automatic execution of all remaining steps at {datetime.now().isoformat()}..."
    )
    event_bus.publish("workflow_auto_run_started", {"project_id": project_id})
    try:
        project = engine.execute_all(project_id, allow_all=True)
        if project.steps_history:
            last_step = project.steps_history[-1]
            for step_log in last_step.logs:
                if step_log not in log_handler.logs[project_id]:
                    log_handler.logs[project_id].append(step_log)
        payload_out = _step_event_payload(project_id, project)
        event_bus.publish("workflow_auto_run_completed", payload_out)
        return project.to_dict()
    except Exception as e:
        log_handler.logs[project_id].append(f"[ERROR] Auto-run failed: {str(e)}")
        event_bus.publish("step_failed", {"project_id": project_id, "error": str(e)})
        raise HTTPException(status_code=500, detail=f"Auto-run error: {str(e)}")
    finally:
        active_executions.discard(project_id)


@app.get("/api/projects/{project_id}/logs")
def get_project_execution_logs(project_id: str):
    lines = log_handler.logs.get(project_id)
    if not lines:
        return ["No active logs found for this project."]
    return list(lines)


@app.get("/api/system/logs")
def get_system_logs(
    level: str = "ALL",
    source: str = "all",
    limit: int = 250,
    search: Optional[str] = None,
):
    """Retrieve structured system and error logs for the Studio UI."""
    from core.paths import LOGS_DIR
    import re
    limit = max(10, min(1000, limit))
    level_filter = level.upper()

    log_files = []
    if source in ("all", "app"):
        app_log = os.path.join(LOGS_DIR, "app.log")
        if os.path.exists(app_log):
            log_files.append(("app", app_log))
    if source in ("all", "studio"):
        studio_log = os.path.join(LOGS_DIR, "studio.log")
        if os.path.exists(studio_log):
            log_files.append(("studio", studio_log))

    parsed_entries = []
    error_count = 0
    warning_count = 0

    app_pattern = re.compile(
        r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[,\.]\d{3})\s+\[(\w+)\]\s+\[([^\]]+)\]\s+(?:\[[^\]]*\]\s*-\s*)?(.*)$"
    )
    studio_pattern = re.compile(
        r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[,\.]\d{3})\s+(\w+)\s+([\w\.\-]+):\s*(.*)$"
    )

    for src_name, file_path in log_files:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[-800:]
                current_entry = None
                for line in lines:
                    line_str = line.rstrip()
                    if not line_str:
                        continue
                    m = app_pattern.match(line_str) or studio_pattern.match(line_str)
                    if m:
                        ts, lvl, comp, msg = m.groups()
                        lvl_norm = lvl.upper()
                        if lvl_norm in ("CRITICAL", "ERROR"):
                            error_count += 1
                        elif lvl_norm in ("WARNING", "WARN"):
                            warning_count += 1

                        current_entry = {
                            "timestamp": ts,
                            "level": lvl_norm,
                            "logger": comp.strip(),
                            "message": msg.strip(),
                            "source": src_name,
                            "traceback": [],
                        }
                        parsed_entries.append(current_entry)
                    elif current_entry:
                        current_entry["traceback"].append(line_str)
                        if "error" in line_str.lower() or "exception" in line_str.lower():
                            if current_entry["level"] not in ("ERROR", "CRITICAL"):
                                current_entry["level"] = "ERROR"
                                error_count += 1
                    else:
                        is_err = "error" in line_str.lower() or "exception" in line_str.lower()
                        if is_err:
                            error_count += 1
                        parsed_entries.append({
                            "timestamp": "",
                            "level": "ERROR" if is_err else "INFO",
                            "logger": src_name,
                            "message": line_str,
                            "source": src_name,
                            "traceback": [],
                        })
        except Exception as e:
            logger.warning("Failed reading log file %s: %s", file_path, e)

    filtered = []
    for entry in parsed_entries:
        if level_filter != "ALL":
            if level_filter == "ERROR" and entry["level"] not in ("ERROR", "CRITICAL"):
                continue
            elif level_filter == "WARNING" and entry["level"] not in ("WARN", "WARNING", "ERROR", "CRITICAL"):
                continue
            elif level_filter not in entry["level"]:
                continue

        if search and search.strip():
            st = search.strip().lower()
            text_corpus = f"{entry.get('message', '')} {entry.get('logger', '')} {' '.join(entry.get('traceback', []))}".lower()
            if st not in text_corpus:
                continue

        filtered.append(entry)

    filtered.reverse()
    clipped = filtered[:limit]

    return {
        "status": "ok",
        "total_parsed": len(parsed_entries),
        "error_count": error_count,
        "warning_count": warning_count,
        "returned": len(clipped),
        "level_filter": level_filter,
        "logs": clipped,
    }


@app.post("/api/system/logs/clear")
def clear_system_logs():
    """Clear memory logs and truncate log files safely."""
    from core.paths import LOGS_DIR
    log_handler.logs.clear()
    cleared_files = []
    for name in ("app.log", "studio.log"):
        p = os.path.join(LOGS_DIR, name)
        if os.path.exists(p):
            try:
                with open(p, "w", encoding="utf-8") as f:
                    f.truncate(0)
                cleared_files.append(name)
            except Exception as e:
                logger.warning("Could not truncate %s: %s", name, e)
    return {"status": "ok", "cleared": cleared_files}


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


@app.get("/api/projects/{project_id}/asset/{asset_name}/print", response_class=HTMLResponse)
def print_project_asset(project_id: str, asset_name: str, auto: int = Query(0)):
    try:
        project = Project.load(project_id)
        asset_file = project.assets.get(asset_name)
        if not asset_file:
            raise HTTPException(status_code=404, detail="Asset not generated yet")

        project_dir = os.path.realpath(project.get_project_dir())
        file_path = os.path.realpath(os.path.join(project_dir, asset_file))
        if not file_path.startswith(project_dir + os.sep) or not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="Asset file missing on disk")

        with open(file_path, "r", encoding="utf-8") as f:
            raw_content = f.read()

        escaped_content = html.escape(raw_content)
        auto_script = "<script>window.addEventListener('load', () => { setTimeout(() => window.print(), 350); });</script>" if auto else ""

        html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{html.escape(project.name)} - {html.escape(asset_name)}</title>
  <style>
    @page {{
      margin: 0.5in;
      margin-top: 0.5in;
      margin-bottom: 0.5in;
      margin-left: 0.5in;
      margin-right: 0.5in;
      size: auto;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      color: #111827;
      background: #ffffff;
      margin: 0;
      padding: 24px;
      line-height: 1.6;
      font-size: 11pt;
    }}
    .no-print {{
      margin-bottom: 24px;
      padding: 12px 18px;
      background: #f1f5f9;
      border: 1px solid #cbd5e1;
      border-radius: 8px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .no-print button {{
      background: #2563eb;
      color: #ffffff;
      border: none;
      padding: 8px 16px;
      border-radius: 6px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
    }}
    .no-print button:hover {{
      background: #1d4ed8;
    }}
    .header {{
      border-bottom: 2px solid #0f172a;
      padding-bottom: 12px;
      margin-bottom: 20px;
    }}
    .header h1 {{
      font-size: 22px;
      font-weight: 700;
      margin: 0 0 6px 0;
      color: #0f172a;
      text-transform: capitalize;
    }}
    .header .meta {{
      font-size: 13px;
      color: #475569;
      display: flex;
      flex-wrap: wrap;
      gap: 16px;
    }}
    .content {{
      font-size: 11pt;
      line-height: 1.65;
    }}
    pre {{
      background: #f8fafc;
      border: 1px solid #cbd5e1;
      border-radius: 6px;
      padding: 16px;
      font-family: Consolas, "Liberation Mono", Menlo, Courier, monospace;
      font-size: 10pt;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.55;
      color: #0f172a;
    }}
    @media print {{
      .no-print {{
        display: none !important;
      }}
      body {{
        padding: 0 !important;
      }}
    }}
  </style>
</head>
<body>
  <div class="no-print">
    <div>
      <strong>Print Document:</strong> {html.escape(project.name)} &bull; {html.escape(asset_file)}
      <div style="font-size: 12px; color: #64748b; margin-top: 2px;">
        Standard browser print dialog with full printer detection. (Shortcut: Ctrl + P)
      </div>
    </div>
    <div style="display: flex; gap: 8px;">
      <button onclick="window.print()">🖨️ Print to Printer</button>
      <button onclick="window.close()" style="background:#64748b;">Close Tab</button>
    </div>
  </div>

  <div class="header">
    <h1>{html.escape(asset_name.replace('_', ' '))}</h1>
    <div class="meta">
      <span><strong>Project:</strong> {html.escape(project.name)}</span>
      <span><strong>Channel:</strong> {html.escape(project.brand)}</span>
      <span><strong>File:</strong> {html.escape(asset_file)}</span>
      <span><strong>Printed:</strong> {datetime.now().strftime("%b %d, %Y %I:%M %p")}</span>
    </div>
  </div>

  <div class="content">
    <pre>{escaped_content}</pre>
  </div>

  {auto_script}
</body>
</html>
"""
        return HTMLResponse(content=html_body)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/projects/{project_id}/asset/{asset_name}/open_browser_print")
def open_browser_print(project_id: str, asset_name: str):
    try:
        from core.paths import BUZZCAF_PORT
        port = os.getenv("BUZZCAF_PORT", "8099")
        url = f"http://127.0.0.1:{port}/api/projects/{project_id}/asset/{asset_name}/print?auto=1"
        webbrowser.open(url)
        return {"status": "opened", "url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

from core.agent import AgentFactory

class TopicDiscoverSchema(BaseModel):
    channel: str
    sources: Optional[List[str]] = None
    pillar_filter: Optional[str] = None

SEED_TOPICS_DIR = os.path.join(KNOWLEDGE_DIR, "seed_topics")

_seed_topics_cache: Optional[Dict[str, List[Dict[str, Any]]]] = None


def _channel_slug(name: str) -> str:
    """Canonical key for a channel name.

    Legacy spellings ('Spilled Coffee Studio', 'After Dark') and the current
    brand names ('Originals', 'Raat3Baje') refer to the same channels; comparing
    slugs avoids the old two-way substring match, under which a short name could
    match an unrelated longer one.
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


DISCOVER_JSON_INSTRUCTION = """
### Required Output Format (JSON only)
Reply with a single JSON object and nothing else:

{
  "topics": [
    {
      "topic": "the video title, in Hinglish",
      "category": "which channel pillar this belongs to",
      "viral_potential": 8,
      "country": "India | International | Global",
      "source_type": "where the story comes from",
      "sources_used": ["a real, checkable reference"],
      "visual_requirements": ["archive footage, maps, diagrams you would need"],
      "notes": "the angle, in one line"
    }
  ]
}

Give six topics. Do not repeat anything in "Already saved". Do not invent a
source: leave "sources_used" empty rather than filling it with a plausible name.
"""


def _discover_prompt(channel: str) -> str:
    """Channel guide + what is already saved, so the agent proposes new angles."""
    from app.services.studio_chat import channel_guide

    saved = [t for t in _load_saved_topics() if _channel_slug(t.get("channel", "")) == _channel_slug(channel)]
    parts = [f"Propose fresh video topics for the channel '{channel}'."]
    guide = channel_guide(channel)
    if guide:
        parts.append(f"\n\n## Brand guide for {channel}\n{guide}")
    if saved:
        titles = "\n".join(f"- {t.get('topic')}" for t in saved[:30])
        parts.append(f"\n\n## Already saved (do not repeat)\n{titles}")
    parts.append(DISCOVER_JSON_INSTRUCTION)
    return "".join(parts)


def _parse_discovered_topics(raw_output: Any, channel: str) -> List[Dict[str, Any]]:
    """The agent's topic list, or [] when it did not answer in the schema."""
    from integrations.llm import clean_json_response

    text = str(raw_output)
    try:
        parsed = json.loads(clean_json_response(text))
    except Exception as e:
        logger.warning(f"Topic discovery reply was not clean JSON, trying tolerant extraction: {e}")
        try:
            from app.services.video_intel import _extract_json

            parsed = _extract_json(text)
        except Exception as e2:
            logger.warning(f"Topic discovery tolerant extraction also failed: {e2}")
            parsed = None
        if parsed is None:
            return []
    items = parsed.get("topics") if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        return []
    topics = []
    for item in items:
        if not isinstance(item, dict) or not str(item.get("topic", "")).strip():
            continue
        item.setdefault("channel", channel)
        topics.append(item)
    return topics


def _seed_topics_response(
    channel: str,
    target_agent_name: str,
    source: str,
    reason: str,
    fallback_source: Optional[str] = None,
) -> Dict[str, Any]:
    """Serve the curated seed topics for a channel, labelled with why."""
    channel_vaults = _load_seed_topics()
    requested = _channel_slug(channel)
    for name, seed_topics in channel_vaults.items():
        if _channel_slug(name) == requested:
            return {
                "status": "success",
                "source": source,
                "channel": name,
                "agent_assigned": target_agent_name,
                "topics": seed_topics,
                "reason": reason,
            }

    # Unknown channel: fall back to the general-interest vault, and say so.
    fallback = channel_vaults.get("Beyond3Baje", [])
    return {
        "status": "success",
        "source": fallback_source or source,
        "channel": channel,
        "agent_assigned": target_agent_name,
        "topics": fallback,
        "reason": reason,
    }


@app.post("/api/topics/discover")
def discover_channel_topics(payload: TopicDiscoverSchema):
    """Fresh topics from the channel's own strategist.

    Until v9 this endpoint only ever served the curated seed files. It now asks
    the agent first and keeps the seed list as the labelled fallback for when no
    provider answered -- the `source` field says which one you are looking at.
    """
    channel = payload.channel.strip()

    agent_map = {
        "originals": "SpilledCoffeeStudioStrategist",
        "spilledcoffeestudio": "SpilledCoffeeStudioStrategist",
        "raat3baje": "AfterDarkStrategist",
        "spilledcoffeeafterdark": "AfterDarkStrategist",
        "beyond3baje": "Beyond3BajeStrategist",
        "life3baje": "Life3BajeStrategist",
        "khayal3baje": "Khayal3BajeStrategist"
    }
    target_agent_name = agent_map.get(_channel_slug(channel), "TopicVaultManager")

    topics: List[Dict[str, Any]] = []
    model_answered = False
    try:
        agent = AgentFactory.get_agent(target_agent_name, engine.llm_service)
        raw = agent.execute(_discover_prompt(channel), require_json=True)
        model_answered = not getattr(agent.llm_service, "last_response_simulated", False)
        if not model_answered:
            logger.warning("Topic discovery got no model response; falling back to the seed list.")
        else:
            topics = _parse_discovered_topics(raw, channel)
    except Exception as e:
        logger.error(f"Topic discovery via {target_agent_name} failed: {e}")

    if topics:
        return {
            "status": "success",
            "source": "model",
            "channel": channel,
            "agent_assigned": target_agent_name,
            "topics": topics,
            "reason": "",
        }

    if model_answered:
        # A real model replied, but not with a parseable topic list: say so
        # plainly rather than silently mislabelling this as the curated seed.
        return _seed_topics_response(
            channel,
            target_agent_name,
            source="model_unparsed",
            reason="The model replied but not as a topic list, so these are curated starter topics. Try Reload.",
        )

    # No model answered at all: serve the curated seed topics and say so,
    # with an actionable reason for why there was nothing else to show.
    return _seed_topics_response(
        channel,
        target_agent_name,
        source="curated_seed",
        fallback_source="curated_seed_fallback",
        reason="No model answered. Start your local model (LM Studio :1234 or llama.cpp :8089) or pick a provider in Settings.",
    )


class TopicValidateSchema(BaseModel):
    topic: str
    channel: Optional[str] = None
    force: Optional[bool] = False


@app.post("/api/topics/validate")
def validate_topic_endpoint(payload: TopicValidateSchema):
    """Check whether a topic is worth making before it becomes a project.

    Gathers YouTube competition (keyless yt-dlp search), general web interest and
    a best-effort Google Trends read, then returns a make/refine/skip verdict.
    Returns 200 with a labelled `simulated` verdict when no model is reachable.
    """
    topic = (payload.topic or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="A topic is required.")
    try:
        from app.services.topic_validation import validate_topic
        return validate_topic(topic, payload.channel, bool(payload.force))
    except Exception as e:
        logger.error(f"Topic validation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Topic validation failed: {e}")


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
    stage: Optional[str] = None
    added_by: Optional[str] = None
    tags: Optional[List[str]] = []

def _load_saved_topics() -> List[Dict[str, Any]]:
    from app.services import topic_store

    return topic_store.load_topics()

def _save_saved_topics(topics: List[Dict[str, Any]]):
    from app.services import topic_store

    topic_store.save_topics(topics)

@app.get("/api/topics/saved")
def get_saved_topics(channel: Optional[str] = None):
    topics = _load_saved_topics()
    if channel and channel.strip():
        topics = [t for t in topics if channel.lower() in t.get("channel", "").lower()]
    return {"status": "success", "count": len(topics), "topics": topics}

@app.post("/api/topics/save")
def save_topic(payload: SavedTopicSchema):
    from app.services import topic_store

    stored = topic_store.add_topic(payload.model_dump(), added_by=(payload.added_by or "user"), stage=payload.stage)
    return {"status": "success", "message": "Topic saved to vault successfully", "topic": stored}

@app.post("/api/topics/delete")
def delete_saved_topic(payload: Dict[str, Any] = Body(...)):
    from app.services import topic_store

    remaining = topic_store.delete_topic(topic_id=payload.get("id"), topic=payload.get("topic"))
    return {"status": "success", "message": "Topic removed from vault", "remaining": remaining}

class TopicUpdateSchema(BaseModel):
    model_config = {"extra": "allow"}

    id: str
    stage: Optional[str] = None
    notes: Optional[str] = None

@app.post("/api/topics/update")
def update_saved_topic(payload: TopicUpdateSchema):
    from app.services import topic_store

    fields = {k: v for k, v in payload.model_dump().items() if k != "id" and v is not None}
    if "stage" in fields and fields["stage"] not in topic_store.STAGES:
        return JSONResponse(status_code=400, content={"status": "error", "message": "invalid stage"})

    updated = topic_store.update_topic(payload.id, fields)
    if updated is None:
        return JSONResponse(status_code=404, content={"status": "error", "message": "topic not found"})
    return {"status": "success", "topic": updated}

IDEA_DUMP_FILE = os.path.join(os.path.dirname(__file__), "..", "knowledge", "idea_dump.json")

class IdeaDumpItemSchema(BaseModel):
    id: str
    title: str
    notes: Optional[str] = ""
    channel: Optional[str] = ""
    createdAt: Optional[str] = None

def _load_idea_dump() -> List[Dict[str, Any]]:
    # Plain JSON on disk; the file only grows until the user deletes it. A
    # missing file means "empty", and a corrupt file is left untouched (we
    # never overwrite what we could not read).
    if not os.path.exists(IDEA_DUMP_FILE):
        return []
    try:
        with open(IDEA_DUMP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
    except Exception:
        pass
    return []

def _save_idea_dump(ideas: List[Dict[str, Any]]):
    # Atomic write (temp file + replace) so a crash mid-write cannot corrupt
    # the user's ideas.
    os.makedirs(os.path.dirname(IDEA_DUMP_FILE), exist_ok=True)
    tmp = IDEA_DUMP_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ideas, f, indent=2)
    os.replace(tmp, IDEA_DUMP_FILE)

@app.get("/api/idea-dump")
def get_idea_dump():
    ideas = _load_idea_dump()
    return {"status": "success", "count": len(ideas), "ideas": ideas}

@app.post("/api/idea-dump")
def put_idea_dump(payload: Dict[str, Any] = Body(...)):
    """Replace the whole idea dump. The frontend sends its full local list on
    every change (single user, no concurrency concerns)."""
    raw = payload.get("ideas")
    if not isinstance(raw, list):
        return JSONResponse(status_code=400, content={"status": "error", "message": "Expected {'ideas': [...]}."})
    ideas: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or not str(item.get("title", "")).strip():
            continue
        idea = {
            "id": str(item.get("id") or f"dump_{uuid.uuid4().hex[:8]}"),
            "title": str(item["title"]).strip(),
            "notes": str(item.get("notes", "")),
            "channel": str(item.get("channel", "")),
            "createdAt": str(item.get("createdAt") or datetime.now().isoformat()),
        }
        ideas.append(idea)
    _save_idea_dump(ideas)
    return {"status": "success", "message": "Idea dump saved to disk", "count": len(ideas)}

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
    """The Studio Assistant turn. See app/services/studio_chat.run_chat."""
    from app.services.studio_chat import run_chat

    agent_name = (payload.agent_name or "").strip()
    try:
        return run_chat(
            message=payload.message,
            channel=payload.channel,
            agent_name=agent_name or None,
            history=payload.chat_history,
            context_topic=payload.context_topic,
        )
    except Exception as e:
        logger.error(f"Studio chat failed for {agent_name or payload.channel}: {e}", exc_info=True)
        # A failed call is an HTTP failure, not a 200 with an apology inside:
        # Dexter's client checks res.ok, and the UI shows the detail in a toast.
        detail = f"{agent_name or 'The strategist'} could not be reached: {e}"
        return JSONResponse(
            status_code=502,
            content={
                "status": "error",
                "simulated": True,
                "error": str(e),
                "detail": detail,
                "agent_name": agent_name,
                "channel": payload.channel,
                "reply": f"**{agent_name or 'Strategist'}** could not be reached: {e}\n\n"
                         "Check your provider settings and that the selected model is available.",
            },
        )


@app.get("/api/agents")
def get_all_agents(department: Optional[str] = None):
    """The registered personas with their frontmatter.

    Before v9 this listed the directory and invented `status: "Active & Idle"`,
    which was neither true nor knowable. It now reports what the registry holds:
    a persona is `registered` or it is not here at all.
    """
    from core.agent import agent_registry

    wanted = (department or "").strip().lower()
    agents = []
    for a_def in agent_registry.agents.values():
        if wanted and a_def.department.lower() != wanted:
            continue
        agents.append({
            "name": a_def.name,
            "department": a_def.department,
            "role": a_def.role,
            "inputs": a_def.inputs,
            "outputs": a_def.outputs,
            "dependencies": a_def.dependencies,
            "version": a_def.version,
            "model_tier": a_def.model_tier,
            "temperature": a_def.temperature,
            "status": "registered",
            "file": os.path.basename(a_def.prompt_filepath) if a_def.prompt_filepath else f"{a_def.name}.md",
        })
    agents.sort(key=lambda a: (a["department"], a["name"]))
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


# ───────────────────────── headless entry (no window) ─────────────────────────
#
# `python backend/desktop_app.py` opens the WebView2 window. Dexter's
# buzzcaf_client documents an API-only fallback (`uvicorn app.main:app`); this
# entry is that fallback done by the book: it picks its own port instead of
# being handed one, publishes itself to the shared ledger, prints `READY port=N`
# so a launcher can open the port we actually took, and withdraws on exit.
#
#     cd backend && python -m app.main [--port N] [--host H]


def serve_headless(preferred: int | None = None, host: str = "127.0.0.1") -> int:
    import atexit
    import socket

    import uvicorn

    from integrations import buzzcaf_ports

    preferred = int(preferred if preferred is not None else PREFERRED_PORT)
    port = buzzcaf_ports.pick_port(preferred, host=host)
    set_bound_port(port)
    os.environ["BUZZCAF_PORT"] = str(port)
    health_url = f"http://{host}:{port}/health"

    # Publish once the socket is really ours. uvicorn binds before serving, so a
    # thread that waits for /health to answer is the honest signal; a bound
    # socket that never answers must not leave an entry behind.
    import threading
    import urllib.request

    def _publish_when_up() -> None:
        for _ in range(120):
            try:
                with urllib.request.urlopen(health_url, timeout=1) as res:
                    if res.status == 200 and json.loads(res.read().decode("utf-8") or "{}").get("app") == APP_ID:
                        break
            except Exception:
                pass
            import time as _time

            _time.sleep(0.25)
        else:
            return
        buzzcaf_ports.publish(APP_ID, port, health_url)
        print(f"READY port={port}", flush=True)

    threading.Thread(target=_publish_when_up, name="buzzcaf-publish", daemon=True).start()
    # This process owns the entry, so the shutdown hook (and these two
    # backstops) may remove it.
    global _owns_ledger_entry
    _owns_ledger_entry = True
    atexit.register(_withdraw_ledger_entry)
    if port != preferred:
        print(f"[buzzcaf] port {preferred} was busy; stepped forward to {port}", flush=True)
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    finally:
        _withdraw_ledger_entry()
    del socket
    return 0


if __name__ == "__main__":
    import argparse
    import sys

    _parser = argparse.ArgumentParser(description="Buzzcaf Studio backend (headless)")
    _parser.add_argument("--port", type=int, default=None, help="preferred port (default: BUZZCAF_PORT or 8099)")
    _parser.add_argument("--host", default="127.0.0.1")
    _args = _parser.parse_args()
    sys.exit(serve_headless(_args.port, _args.host))
