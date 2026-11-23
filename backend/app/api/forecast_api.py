"""Model routing, model usage and the nightly forecast (2026-10-26).

GET  /api/llm/routes          every job's route {provider, model, fallback}, the choices, Claude tokens per job
PUT  /api/llm/routes          {routes: {job: {provider, model, fallback}}}
GET  /api/llm/usage?days=7    calls, tokens and seconds per job and provider (integrations/llm_usage.py)
GET  /api/forecast/nightly    tonight's long-form run: per slot and step, times, the deadline, Claude tokens
GET  /api/forecast/preflight  the checks that catch a failing night before it starts (?fresh=1 re-runs them)
POST /api/forecast/fix        {id}: one of the fixes a check offers
GET  /api/forecast/live       the running batch against the forecast, slow and failed slots, a dead run
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import run_forecast
from integrations import llm, llm_usage

router = APIRouter(tags=["forecast"])

CLAUDE_MODELS = ["opus", "sonnet", "haiku"]


class RoutesSchema(BaseModel):
    routes: Optional[Dict[str, Dict[str, Optional[str]]]] = None        # day
    routes_night: Optional[Dict[str, Dict[str, Optional[str]]]] = None  # night
    night_hours: Optional[Dict[str, str]] = None                       # {start, end} "HH:MM"


class FixSchema(BaseModel):
    id: str


def _ollama_models() -> list:
    try:
        import requests
        r = requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
        return [m.get("name") for m in r.json().get("models", []) if m.get("name")]
    except Exception:  # noqa: BLE001 - Ollama down: no choices
        return []


@router.get("/api/llm/routes")
def get_routes() -> Dict[str, Any]:
    cfg = llm.load_config()
    day = llm.job_routes(cfg, profile="day")
    night = llm.job_routes(cfg, profile="night")
    usage = llm_usage.averages(days=7)
    return {
        "jobs": [{"key": k, "label": label, "day": day[k], "night": night[k], "measured": usage.get(k, {})}
                 for k, label in llm.LLM_JOBS.items()],
        "night_hours": llm.night_hours(cfg),
        "profile_now": llm.route_profile(cfg),
        "providers": [p for p in llm.ROUTE_PROVIDERS if p],
        "claude_models": CLAUDE_MODELS,
        "gemma_model": cfg.get("lm_studio_model") or "",
        "ollama_models": _ollama_models(),
        "gemini_model": cfg.get("gemini_model") or "flash",
        "claude_ready": llm.claude_configured(cfg),
    }


def _clean_routes(routes: Dict[str, Dict[str, Optional[str]]], current: Dict[str, Dict[str, str]]):
    for job, entry in routes.items():
        if job not in llm.LLM_JOBS:
            raise HTTPException(status_code=400, detail=f"unknown job: {job}")
        clean = {k: str((entry or {}).get(k) or "").strip() for k in ("provider", "model", "fallback")}
        for key in ("provider", "fallback"):
            if clean[key] not in llm.ROUTE_PROVIDERS:
                raise HTTPException(status_code=400, detail=f"{job}: unknown {key} '{clean[key]}'")
        if clean["fallback"] == clean["provider"]:
            clean["fallback"] = ""
        current[job] = clean
    return current


@router.put("/api/llm/routes")
def put_routes(body: RoutesSchema) -> Dict[str, Any]:
    import re
    cfg = llm.load_config()
    if body.routes is not None:
        cfg["job_routes"] = _clean_routes(body.routes, llm.job_routes(cfg, profile="day"))
    if body.routes_night is not None:
        cfg["job_routes_night"] = _clean_routes(body.routes_night, llm.job_routes(cfg, profile="night"))
    if body.night_hours is not None:
        hours = {k: str(body.night_hours.get(k) or "").strip() for k in ("start", "end")}
        if not all(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v) for v in hours.values()):
            raise HTTPException(status_code=400, detail="night hours are HH:MM")
        cfg["night_hours"] = hours
    llm.save_config(cfg)
    run_forecast.clear_cache()
    return get_routes()


@router.get("/api/llm/usage")
def get_usage(days: float = 7.0) -> Dict[str, Any]:
    return llm_usage.summary(days=max(0.1, min(days, 90.0)))


@router.get("/api/forecast/nightly")
def get_forecast() -> Dict[str, Any]:
    return run_forecast.forecast()


@router.get("/api/forecast/preflight")
def get_preflight(fresh: bool = False) -> Dict[str, Any]:
    return run_forecast.preflight(fresh=fresh)


@router.post("/api/forecast/fix")
def post_fix(body: FixSchema) -> Dict[str, Any]:
    try:
        return run_forecast.fix(body.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/forecast/live")
def get_live() -> Dict[str, Any]:
    return run_forecast.live()
