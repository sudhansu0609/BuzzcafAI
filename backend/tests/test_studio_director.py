"""Studio Director (docs/STUDIO_DIRECTOR_PLAN.md Part 3): the snapshot, the
planner's strategist loop, the MAKE allowlist vs. the approval gate,
learning from the decision log without touching the creator's own rules,
the morning briefing, and the `/api/director/*` routes."""
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.services import studio_director


@pytest.fixture
def director_sandbox(monkeypatch, tmp_path):
    """Every test gets its own `knowledge/director/` and decisions log --
    never the real sandbox the rest of the suite shares."""
    monkeypatch.setattr(studio_director, "DIRECTOR_DIR", str(tmp_path / "director"))
    monkeypatch.setattr(studio_director, "KNOWLEDGE_DIR", str(tmp_path))
    return tmp_path


def _fast_health(monkeypatch):
    """`snapshot()` calls `health_checks.run_all()`, which otherwise probes
    real local ports; a unit test must not do that."""
    from app.services import health_checks
    monkeypatch.setattr(health_checks, "run_all",
                        lambda: {"overall": "ok", "counts": {"ok": 1}, "checks": []})


# --- snapshot ---------------------------------------------------------------------------

def test_snapshot_shape(director_sandbox, monkeypatch):
    _fast_health(monkeypatch)
    snap = studio_director.snapshot()
    assert "at" in snap
    assert set(studio_director.CHANNELS) <= set(snap["channels"].keys())
    for ch in studio_director.CHANNELS:
        bucket = snap["channels"][ch]
        assert set(bucket.keys()) >= {"recent", "needs_review", "failed"}
    assert "master_pause" in snap
    assert "health" in snap
    assert "approvals_pending" in snap


def test_snapshot_never_raises_when_a_subsystem_is_broken(director_sandbox, monkeypatch):
    _fast_health(monkeypatch)
    from app.services import auto_story
    monkeypatch.setattr(auto_story, "list_records", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    snap = studio_director.snapshot()
    assert "auto_story_error" in snap
    assert snap["channels"][studio_director.CHANNELS[0]] == {"recent": [], "needs_review": [], "failed": []}


# --- plan ---------------------------------------------------------------------------------

def test_plan_recomputes_needs_approval_from_the_make_allowlist(director_sandbox, monkeypatch):
    _fast_health(monkeypatch)
    from app.services import strategist_runner

    fake_plan = {"items": [
        {"channel": "Raat3Baje", "action": "auto_story_make", "params": {"format": "rules_horror"},
         "when": "tonight", "why": "weekly reel", "needs_approval": True},   # must be recomputed to False
        {"channel": "Beyond3Baje", "action": "publish_youtube", "params": {"project_id": "p1"},
         "when": "today", "why": "ready", "needs_approval": False},         # must be recomputed to True
    ]}
    monkeypatch.setattr(strategist_runner, "run", lambda *a, **k: {"plan": fake_plan, "turns": 1, "calls": []})

    result = studio_director.plan("day")
    by_action = {it["action"]: it for it in result["items"]}
    assert by_action["auto_story_make"]["needs_approval"] is False
    assert by_action["publish_youtube"]["needs_approval"] is True
    assert result["horizon"] == "day"

    stored = studio_director.read_plan()
    assert stored["items"] == result["items"]


def test_plan_rejects_a_bad_horizon(director_sandbox):
    with pytest.raises(ValueError):
        studio_director.plan("month")


def test_plan_drops_items_with_no_action(director_sandbox, monkeypatch):
    from app.services import strategist_runner
    monkeypatch.setattr(strategist_runner, "run", lambda *a, **k: (
        {"plan": {"items": [{"channel": "Raat3Baje", "action": ""}]}, "turns": 1, "calls": []}))
    result = studio_director.plan("day")
    assert result["items"] == []


# --- act: MAKE items run, everything else becomes an approval ------------------------------

def test_act_runs_make_items_and_queues_approvals_for_everything_else(director_sandbox, monkeypatch):
    ran = []
    monkeypatch.setattr(studio_director, "_run_make_action",
                        lambda action, channel, params, say: ran.append((action, channel, params)) or "done")

    plan_obj = {"items": [
        {"channel": "Raat3Baje", "action": "auto_story_make", "params": {"format": "rules_horror"}},
        {"channel": "Beyond3Baje", "action": "publish_youtube", "params": {"project_id": "p1"}},
    ]}
    result = studio_director.act(plan_obj)

    statuses = {r["item"]["action"]: r["status"] for r in result["results"]}
    assert statuses["auto_story_make"] == "ran"
    assert statuses["publish_youtube"] == "approval_requested"
    assert ran == [("auto_story_make", "Raat3Baje", {"format": "rules_horror"})]

    pending = studio_director.list_approvals("pending")
    assert len(pending) == 1
    assert pending[0]["item"]["action"] == "publish_youtube"


def test_act_records_a_failed_make_item_without_stopping_the_rest(director_sandbox, monkeypatch):
    calls = []

    def fake_run(action, channel, params, say):
        calls.append(action)
        if action == "auto_story_make":
            raise RuntimeError("no topic")
        return "ok"

    monkeypatch.setattr(studio_director, "_run_make_action", fake_run)
    plan_obj = {"items": [
        {"channel": "Raat3Baje", "action": "auto_story_make", "params": {}},
        {"channel": "Beyond3Baje", "action": "retry_record", "params": {"item_id": "x"}},
    ]}
    result = studio_director.act(plan_obj)
    statuses = {r["item"]["action"]: r["status"] for r in result["results"]}
    assert statuses["auto_story_make"] == "failed"
    assert statuses["retry_record"] == "ran"
    assert calls == ["auto_story_make", "retry_record"]


def test_master_pause_holds_act(director_sandbox, monkeypatch, tmp_path):
    from app.services import master_control
    monkeypatch.setattr(master_control, "STATE_PATH", str(tmp_path / "master_control.json"))
    master_control._state_cache = None
    master_control._held.clear()
    monkeypatch.setattr(master_control, "_pause_buzzedit", lambda mode, reason="", by="": {})
    monkeypatch.setattr(master_control, "_resume_buzzedit", lambda: {})
    monkeypatch.setattr(master_control, "_release_memory", lambda reason: {})
    monkeypatch.setattr(master_control, "POLL_S", 0.02)

    ran = []
    monkeypatch.setattr(studio_director, "_run_make_action",
                        lambda action, channel, params, say: ran.append(action))

    master_control.pause(mode="soft", reason="testing")
    finished = threading.Event()

    def worker():
        studio_director.act({"items": [{"channel": "Raat3Baje", "action": "auto_story_make", "params": {}}]})
        finished.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    try:
        deadline = time.time() + 2
        while "studio_director: act auto_story_make" not in master_control.held() and time.time() < deadline:
            time.sleep(0.01)
        assert "studio_director: act auto_story_make" in master_control.held()
        assert not finished.is_set()
        assert ran == []

        master_control.resume()
        assert finished.wait(timeout=2)
        assert ran == ["auto_story_make"]
    finally:
        if master_control.is_paused():
            master_control.resume()
        master_control._state_cache = None
        master_control._held.clear()


# --- approving an approval executes it ------------------------------------------------------

def test_approving_executes_the_action(director_sandbox, monkeypatch):
    from app.services import auto_story
    approved = []
    monkeypatch.setattr(auto_story, "approve", lambda pid: approved.append(pid) or {"state": "approved"})

    row = studio_director.add_approval({"channel": "Raat3Baje", "action": "auto_story_approve",
                                        "params": {"project_id": "proj1"}})
    result = studio_director.approve_approval(row["id"])

    assert approved == ["proj1"]
    assert result["state"] == "approved"
    assert result["result"] == {"state": "approved"}
    assert studio_director.list_approvals("approved")[0]["id"] == row["id"]
    assert studio_director.list_approvals("pending") == []


def test_declining_never_runs_the_action(director_sandbox, monkeypatch):
    from app.services import auto_story
    monkeypatch.setattr(auto_story, "approve", lambda pid: pytest.fail("must not run on decline"))

    row = studio_director.add_approval({"channel": "Raat3Baje", "action": "auto_story_approve",
                                        "params": {"project_id": "proj1"}})
    result = studio_director.decline_approval(row["id"], reason="too similar to last week")
    assert result["state"] == "declined"
    assert result["reason"] == "too similar to last week"


def test_approving_an_unknown_action_records_the_error_rather_than_crashing(director_sandbox):
    row = studio_director.add_approval({"channel": "Raat3Baje", "action": "delete_project", "params": {}})
    result = studio_director.approve_approval(row["id"])
    assert result["state"] == "approved"
    assert "error" in result


# --- learn: the decision log distilled into rules, creator's section preserved -------------

def test_learn_preserves_creator_section_and_distils_rejections(director_sandbox):
    rules_path = studio_director._rules_path()
    import os
    os.makedirs(os.path.dirname(rules_path), exist_ok=True)
    with open(rules_path, "w", encoding="utf-8") as f:
        f.write(
            "# Studio Director -- learned rules\n\n"
            f"{studio_director.CREATOR_SECTION_HEADING}\n\n"
            "- Never post before 7pm IST.\n\n"
            f"{studio_director.LEARNED_SECTION_HEADING}\n\n(old content, must be replaced)\n"
        )

    log_path = studio_director._decisions_log_path()
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        for entry in (
            {"at": "2026-10-20T10:00:00", "channel": "Raat3Baje", "action": "reject", "reason": "too slow start"},
            {"at": "2026-10-22T10:00:00", "channel": "Raat3Baje", "action": "reject", "reason": "too slow start"},
            {"at": "2026-10-23T10:00:00", "channel": "Beyond3Baje", "action": "reject", "reason": "wrong hook"},
        ):
            f.write(json.dumps(entry) + "\n")

    text = studio_director.learn()

    assert "Never post before 7pm IST." in text
    assert "too slow start" in text
    assert "(evidence: 2" in text
    assert "wrong hook" in text
    assert "(old content, must be replaced)" not in text
    # Persisted to disk, not just returned.
    assert studio_director.read_rules() == text


def test_learn_never_touches_a_hand_written_creator_section_even_with_no_decisions(director_sandbox):
    studio_director.set_creator_rules("Only Hinglish titles. No English-only hooks.")
    text = studio_director.learn()
    assert "Only Hinglish titles." in text


def test_ask_appends_a_rule_without_touching_creators_section(director_sandbox, monkeypatch):
    studio_director.set_creator_rules("His own rule, never touched.")

    class FakeLLM:
        last_response_simulated = False

    class FakeAgent:
        llm_service = FakeLLM()

        def execute_messages(self, messages, system_extra=""):
            return "Got it. [RULE: Raat3Baje] Never open on the rules themselves [/RULE]"

    from core.agent import AgentFactory
    monkeypatch.setattr(AgentFactory, "get_agent", staticmethod(lambda name, llm=None: FakeAgent()))

    out = studio_director.ask("From now on, Raat3Baje never opens on the rules.")
    assert out["rule_added"] == {"channel": "Raat3Baje", "text": "Never open on the rules themselves"}
    rules_text = studio_director.read_rules()
    assert "His own rule, never touched." in rules_text
    assert "Never open on the rules themselves" in rules_text


# --- briefing -----------------------------------------------------------------------------

def test_briefing_lists_made_failed_and_needs_you(director_sandbox, monkeypatch):
    fake_snapshot = {
        "channels": {
            "Raat3Baje": {"recent": [{"project_id": "p1", "name": "Ep1", "format": "rules_horror",
                                      "state": "packaged"}],
                         "needs_review": [{"project_id": "p1", "name": "Ep1", "format": "rules_horror"}],
                         "failed": []},
            "Beyond3Baje": {"recent": [], "needs_review": [],
                            "failed": [{"project_id": "p2", "name": "Ep2", "reason": "no model answered"}]},
        },
    }
    monkeypatch.setattr(studio_director, "snapshot", lambda: fake_snapshot)
    studio_director._write_json(studio_director._plan_path(studio_director.today()),
                                {"items": [{"channel": "Raat3Baje", "action": "auto_story_make",
                                           "why": "weekly reel", "needs_approval": False}]})

    text = studio_director.briefing()
    assert "Ep1 (rules_horror, packaged)" in text
    assert "Ep2: no model answered" in text
    assert "Ep1" in text.split("## Needs you today")[1].split("## Today's plan")[0]
    assert "weekly reel" in text
    assert studio_director.read_briefing() == text


def test_briefing_lists_needs_intro_items_from_the_plan(director_sandbox, monkeypatch):
    monkeypatch.setattr(studio_director, "snapshot", lambda: {"channels": {}})
    studio_director._write_json(studio_director._plan_path(studio_director.today()), {"items": [
        {"channel": "Raat3Baje", "action": studio_director.NEEDS_INTRO_ACTION,
         "params": {"project_id": "long1"}, "why": "script at 24 minutes"},
    ]})
    text = studio_director.briefing()
    assert "Needs your on-camera intro: Raat3Baje (long1)" in text


# --- settings -------------------------------------------------------------------------------

def test_settings_default_off_and_round_trips(director_sandbox):
    assert studio_director.settings() == {"autoplan": False, "provider": ""}
    updated = studio_director.set_settings({"autoplan": True})
    assert updated == {"autoplan": True, "provider": ""}
    assert studio_director.settings() == {"autoplan": True, "provider": ""}


# --- the nightly task: respects director_autoplan -------------------------------------------

def test_run_nightly_acts_only_when_autoplan_is_on(director_sandbox, monkeypatch):
    _fast_health(monkeypatch)
    from app.services import strategist_runner
    monkeypatch.setattr(strategist_runner, "run", lambda *a, **k: (
        {"plan": {"items": [{"channel": "Raat3Baje", "action": "auto_story_make", "params": {}}]},
         "turns": 1, "calls": []}))
    acted = []
    monkeypatch.setattr(studio_director, "act", lambda plan_obj, on_event=None: acted.append(plan_obj) or {"results": []})

    off = studio_director.run_nightly()
    assert off["act"] == {"skipped": "director_autoplan is off"}
    assert acted == []

    studio_director.set_settings({"autoplan": True})
    on = studio_director.run_nightly()
    assert acted and on["act"] == {"results": []}


# --- API routes -----------------------------------------------------------------------------

@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_api_snapshot_and_settings_round_trip(director_sandbox, monkeypatch, client):
    _fast_health(monkeypatch)
    res = client.get("/api/director/snapshot")
    assert res.status_code == 200
    assert "channels" in res.json()

    res = client.post("/api/director/settings", json={"autoplan": True})
    assert res.status_code == 200
    assert res.json()["autoplan"] is True
    assert client.get("/api/director/settings").json()["autoplan"] is True


def test_api_plan_and_act_and_approvals(director_sandbox, monkeypatch, client):
    monkeypatch.setattr(studio_director, "plan", lambda horizon: {"horizon": horizon, "items": []})
    res = client.post("/api/director/plan", json={"horizon": "day"})
    assert res.status_code == 200 and res.json()["horizon"] == "day"

    res = client.post("/api/director/plan", json={"horizon": "nonsense"})
    assert res.status_code == 400

    row = studio_director.add_approval({"channel": "Raat3Baje", "action": "publish_youtube", "params": {}})
    res = client.get("/api/director/approvals", params={"state": "pending"})
    assert res.status_code == 200
    assert res.json()["approvals"][0]["id"] == row["id"]

    res = client.post(f"/api/director/approvals/{row['id']}/decline", json={"reason": "not yet"})
    assert res.status_code == 200
    assert res.json()["state"] == "declined"

    res = client.post("/api/director/approvals/does-not-exist/approve")
    assert res.status_code == 404


def test_api_rules_get_and_post(director_sandbox, client):
    res = client.post("/api/director/rules", json={"creator_rules": "Keep thumbnails simple."})
    assert res.status_code == 200
    assert "Keep thumbnails simple." in res.json()["rules"]
    res = client.get("/api/director/rules")
    assert "Keep thumbnails simple." in res.json()["rules"]


def test_api_briefing_404_when_none_written_yet(director_sandbox, client):
    res = client.get("/api/director/briefing", params={"date": "2000-01-01"})
    assert res.status_code == 404


def test_suggestions_and_replan_api(director_sandbox, monkeypatch, client):
    _fast_health(monkeypatch)
    sugg = studio_director.suggestions()
    assert "timestamp" in sugg
    assert "primary" in sugg
    assert "suggestions" in sugg
    assert "stories_in_progress" in sugg
    assert isinstance(sugg["suggestions"], list)

    res = client.get("/api/director/suggestions")
    assert res.status_code == 200
    data = res.json()
    assert "timestamp" in data
    assert "suggestions" in data

    monkeypatch.setattr(studio_director, "plan", lambda horizon: {"horizon": horizon, "items": []})
    res_replan = client.post("/api/director/replan", json={"horizon": "day"})
    assert res_replan.status_code == 200
    assert res_replan.json()["horizon"] == "day"



# --- Director v2: fixes, memory, mission ------------------------------------------------------

def test_fix_guard_cooldown_and_per_key_cap_write_a_ticket(director_sandbox, monkeypatch):
    from app.services import director_fix, master_control
    calls = []
    monkeypatch.setitem(director_fix._SAFE, "fix_kick_queue", lambda params: calls.append(1) or {"kicked": True})
    monkeypatch.setattr(master_control, "is_paused", lambda: False)
    assert director_fix.run_fix("fix_kick_queue", {}, by="t")["ran"]
    assert "cooldown" in director_fix.run_fix("fix_kick_queue", {}, by="t")["refused"]
    monkeypatch.setattr(director_fix, "COOLDOWN_S", 0)
    assert director_fix.run_fix("fix_kick_queue", {}, by="t")["ran"]
    assert director_fix.run_fix("fix_kick_queue", {}, by="t")["ran"]
    assert "refused" in director_fix.run_fix("fix_kick_queue", {}, by="t")
    assert len(calls) == 3
    assert list((director_sandbox / "director" / "tickets").glob("*.md"))


def test_fix_set_config_needs_approval_and_refuses_unsafe_keys(director_sandbox, monkeypatch):
    from app.services import director_fix
    from integrations import llm as llm_mod
    cfg = {"api_key": "x", "timeout_s": 100, "local_only": True}
    monkeypatch.setattr(llm_mod, "load_config", lambda: dict(cfg))
    monkeypatch.setattr(llm_mod, "save_config", lambda c: cfg.update(c))
    with pytest.raises(ValueError):
        director_fix.run_fix("fix_set_config", {"key": "timeout_s", "value": 200}, approved=False)
    assert "refused" in director_fix.run_fix("fix_set_config", {"key": "api_key", "value": "y"}, approved=True)
    assert "refused" in director_fix.run_fix("fix_set_config", {"key": "nope", "value": 1}, approved=True)
    assert "refused" in director_fix.run_fix("fix_set_config", {"key": "timeout_s", "value": "5"}, approved=True)
    out = director_fix.run_fix("fix_set_config", {"key": "timeout_s", "value": 200}, approved=True)
    assert out.get("previous") == 100, out
    assert out["rollback"]["params"] == {"key": "timeout_s", "value": 100}


def test_ask_records_goal_and_conversation_and_shows_the_mission(director_sandbox, monkeypatch):
    from app.services import strategist_runner
    seen = {}

    def fake_chat(agent, channel, message, **kw):
        seen.update(kw)
        return {"reply": "Noted. [GOAL: Upcoming plans] Launch Tall Storyteller Monday [/GOAL]",
                "simulated": False, "provider": "x", "turns": 1}
    monkeypatch.setattr(strategist_runner, "chat", fake_chat)
    monkeypatch.setattr(studio_director, "snapshot", lambda: {})
    out = studio_director.ask("We launch Tall Storyteller on Monday.")
    mission = (director_sandbox / "director" / "mission.md").read_text(encoding="utf-8")
    assert "Launch Tall Storyteller Monday" in mission.split("## From conversation")[1]
    assert "## The creator's mission" in seen["system_extra"] and "history" in seen
    assert "[GOAL" not in out["reply"] and out["goal_added"]
    rows = (director_sandbox / "director" / "conversation.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 2


def test_conversation_is_capped_and_rolled_into_a_summary(director_sandbox):
    from app.services import director_memory
    for i in range(50):
        director_memory.record_turn("user" if i % 2 == 0 else "director", f"turn {i} " + "x" * 500)
    rows = (director_sandbox / "director" / "conversation.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 40
    summary = (director_sandbox / "director" / "conversation_summary.md").read_text(encoding="utf-8")
    assert 0 < len(summary) <= 4000
    assert sum(len(m["content"]) for m in director_memory.conversation_messages()) <= 3000
