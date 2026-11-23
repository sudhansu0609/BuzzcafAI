"""Studio Director (docs/STUDIO_DIRECTOR_PLAN.md Part 3): one master agent
that sees every channel and job, plans the day/week, acts through the
Studio's own services, asks before publishing/deleting/changing settings,
learns from the creator's decisions and writes a morning briefing
(app/services/studio_director.py).

    GET  /api/director/snapshot
    POST /api/director/plan        {horizon?: "day"|"week"} -> the plan
    POST /api/director/act         {plan_id?: str} -> runs that plan's (default:
                                    today's) MAKE items; everything else in it
                                    becomes an approval request
    GET  /api/director/approvals   ?state=pending|approved|declined
    POST /api/director/approvals   {item: {...}} -> a manual approval request
    POST /api/director/approvals/{id}/approve  -> runs it
    POST /api/director/approvals/{id}/decline  {reason?}
    POST /api/director/ask         {message} -> {reply, rule_added}
    GET  /api/director/briefing    ?date=YYYY-MM-DD (default: today)
    POST /api/director/learn       -> rewrites knowledge/director/rules.md
    GET  /api/director/rules
    POST /api/director/rules       {creator_rules} -> just the "Creator's rules" section
    GET  /api/director/settings
    POST /api/director/settings    {autoplan?: bool}
    GET  /api/director/mission     -> {mission}  (his goals, intentions, plans)
    POST /api/director/mission     {text} -> {mission}
    POST /api/director/diagnose    {problem} -> {hypotheses, ran, approvals, ticket, incident_id, resolved, reply}
    POST /api/director/self_check  -> the no-model check-and-fix pass
    GET  /api/director/memory      -> {promises, incidents, tickets, fixes_today, conversation}
    POST /api/director/promises/{id}/done
    POST /api/director/tickets/{name}/close
    POST /api/director/conversation/clear
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import studio_director

router = APIRouter(prefix="/api/director", tags=["Studio Director"])


class PlanBody(BaseModel):
    horizon: Optional[str] = "day"


class ActBody(BaseModel):
    plan_id: Optional[str] = None


class ApprovalItemBody(BaseModel):
    item: Dict[str, Any]


class DeclineBody(BaseModel):
    reason: Optional[str] = None


class AskBody(BaseModel):
    message: str


class RulesBody(BaseModel):
    creator_rules: str


class MissionBody(BaseModel):
    text: str


class DiagnoseBody(BaseModel):
    problem: str


class SettingsBody(BaseModel):
    autoplan: Optional[bool] = None
    provider: Optional[str] = None


@router.get("/snapshot")
def get_snapshot() -> Dict[str, Any]:
    return studio_director.snapshot()


@router.get("/live_activity")
def get_live_activity() -> Dict[str, Any]:
    return studio_director.live_activity()



@router.post("/plan")
def post_plan(body: PlanBody) -> Dict[str, Any]:
    horizon = body.horizon or "day"
    if horizon not in ("day", "week"):
        raise HTTPException(status_code=400, detail="horizon must be 'day' or 'week'")
    try:
        return studio_director.plan(horizon)
    except Exception as exc:  # noqa: BLE001 - no model answered, or an unusable plan
        raise HTTPException(status_code=502, detail=str(exc)[:300])


@router.post("/act")
def post_act(body: ActBody) -> Dict[str, Any]:
    plan_obj = studio_director.read_plan(body.plan_id)
    if not plan_obj:
        raise HTTPException(status_code=404, detail="No plan to act on; POST /api/director/plan first.")
    return studio_director.act(plan_obj)


@router.get("/approvals")
def get_approvals(state: Optional[str] = None) -> Dict[str, Any]:
    return {"approvals": studio_director.list_approvals(state)}


@router.post("/approvals")
def post_approval(body: ApprovalItemBody) -> Dict[str, Any]:
    return studio_director.add_approval(body.item)


@router.post("/approvals/{approval_id}/approve")
def approve_approval(approval_id: str) -> Dict[str, Any]:
    try:
        return studio_director.approve_approval(approval_id)
    except studio_director.ApprovalNotPending as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/approvals/{approval_id}/decline")
def decline_approval(approval_id: str, body: Optional[DeclineBody] = None) -> Dict[str, Any]:
    body = body or DeclineBody()
    try:
        return studio_director.decline_approval(approval_id, reason=body.reason or "")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/ask")
def post_ask(body: AskBody) -> Dict[str, Any]:
    return studio_director.ask(body.message)


@router.get("/briefing")
def get_briefing(date: Optional[str] = None) -> Dict[str, Any]:
    text = studio_director.read_briefing(date)
    if text is None:
        raise HTTPException(status_code=404, detail="No briefing for that date yet.")
    return {"date": date or studio_director.today(), "markdown": text}


@router.post("/learn")
def post_learn() -> Dict[str, Any]:
    return {"rules": studio_director.learn()}


@router.get("/rules")
def get_rules() -> Dict[str, Any]:
    return {"rules": studio_director.read_rules()}


@router.post("/rules")
def post_rules(body: RulesBody) -> Dict[str, Any]:
    return {"rules": studio_director.set_creator_rules(body.creator_rules)}


@router.get("/settings")
def get_settings() -> Dict[str, Any]:
    out = dict(studio_director.settings())
    try:
        from app.services import health_checks
        from integrations.llm import probe_claude, probe_gemini
        out["provider_status"] = {
            "claude": bool(probe_claude(timeout=2)["online"]),
            "gemini": bool(probe_gemini(timeout=2)["online"]),
            "lm_studio": health_checks.check_lm_studio()["state"] == "ok",
        }
    except Exception:  # noqa: BLE001 - status is a nicety
        pass
    return out


@router.post("/settings")
def post_settings(body: SettingsBody) -> Dict[str, Any]:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        return studio_director.set_settings(patch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/docs")
def get_docs() -> Dict[str, Any]:
    from app.services import director_knowledge
    return {"docs": director_knowledge.knowledge_index()}


@router.get("/docs/read")
def get_doc_read(path: str, heading: Optional[str] = None, start: Optional[int] = None,
                 end: Optional[int] = None, grep: Optional[str] = None) -> Dict[str, Any]:
    from app.services import director_knowledge
    try:
        text = director_knowledge.read_doc(path, heading=heading, start=start, end=end, grep=grep)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"path": path, "text": text}


@router.get("/log_digest")
def get_log_digest(hours: int = 24) -> Dict[str, Any]:
    from app.services import director_knowledge
    return {"hours": hours, "patterns": director_knowledge.log_digest(hours)}


@router.get("/llm_status")
def get_llm_status() -> Dict[str, Any]:
    from app.services import director_knowledge
    return director_knowledge.llm_status()


@router.get("/settings_summary")
def get_settings_summary() -> Dict[str, Any]:
    from app.services import director_knowledge
    return director_knowledge.settings_summary()


@router.get("/suggestions")
def get_suggestions() -> Dict[str, Any]:
    return studio_director.suggestions()


@router.post("/replan")
def post_replan(body: Optional[PlanBody] = None) -> Dict[str, Any]:
    horizon = (body.horizon if body else None) or "day"
    try:
        return studio_director.plan(horizon)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:300])


@router.get("/mission")
def get_mission() -> Dict[str, Any]:
    from app.services import director_memory
    return {"mission": director_memory.read_mission()}


@router.post("/mission")
def post_mission(body: MissionBody) -> Dict[str, Any]:
    from app.services import director_memory
    return {"mission": director_memory.set_mission(body.text)}


@router.post("/diagnose")
def post_diagnose(body: DiagnoseBody) -> Dict[str, Any]:
    from app.services import director_fix, master_control
    if master_control.is_paused():
        raise HTTPException(status_code=409, detail="The master pause is on; resume first.")
    if not (body.problem or "").strip():
        raise HTTPException(status_code=400, detail="problem is empty")
    return director_fix.diagnose(body.problem.strip())


@router.post("/self_check")
def post_self_check() -> Dict[str, Any]:
    from app.services import director_fix
    return director_fix.self_check()


@router.get("/memory")
def get_memory() -> Dict[str, Any]:
    from app.services import director_fix, director_memory
    return {
        "promises": director_memory.list_promises("open"),
        "incidents": director_memory.list_incidents(10),
        "tickets": director_fix.list_tickets(),
        "fixes_today": director_fix.fixes_today(),
        "conversation": studio_director._read_jsonl(
            director_memory._path("conversation.jsonl"))[-10:],
    }


@router.post("/promises/{pid}/done")
def post_promise_done(pid: str) -> Dict[str, Any]:
    from app.services import director_memory
    row = director_memory.close_promise(pid)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No such promise: {pid}")
    return row


@router.post("/tickets/{name}/close")
def post_ticket_close(name: str) -> Dict[str, Any]:
    from app.services import director_fix
    try:
        return director_fix.close_ticket(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/conversation/clear")
def post_conversation_clear() -> Dict[str, Any]:
    from app.services import director_memory
    director_memory.clear_conversation()
    return {"cleared": True}
