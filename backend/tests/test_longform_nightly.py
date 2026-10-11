"""The nightly long-form batch: the channel strategist plans each video with
its tools and the creator's instructions; research and script run on that
plan and stop before Visual Plan; the run's live status is written as it goes."""
import json

import pytest

from app.services import longform_nightly, strategist_runner, topic_store


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    from core.models.project import Project
    from executive.project import project_manager
    monkeypatch.setattr(topic_store, "KNOWLEDGE_DIR", str(tmp_path))
    monkeypatch.setattr(longform_nightly, "KNOWLEDGE_DIR", str(tmp_path))
    monkeypatch.setattr("core.paths.KNOWLEDGE_DIR", str(tmp_path))
    monkeypatch.setattr(project_manager, "projects_dir", str(tmp_path / "projects"))
    monkeypatch.setattr("core.models.project._project_dir_for", lambda pid: str(tmp_path / "projects" / pid))
    cfg = {}
    monkeypatch.setattr("integrations.llm.load_config", lambda: cfg)
    (tmp_path / "saved_topics.json").write_text(json.dumps([
        {"id": "r_low", "topic": "Low ghost", "channel": "Raat3Baje", "viral_potential": 3, "stage": "backlog"},
        {"id": "r_high", "topic": "Kuldhara Ki Raat", "channel": "Raat3Baje", "viral_potential": 9, "stage": "backlog"},
        {"id": "r_done", "topic": "Already made", "channel": "Raat3Baje", "viral_potential": 10, "stage": "published"},
        {"id": "l_one", "topic": "Starting small", "channel": "Life3Baje", "viral_potential": 0, "stage": "backlog"},
    ]), encoding="utf-8")
    (tmp_path / "idea_dump.json").write_text(json.dumps([
        {"id": "d2", "title": "Impundulu: Lightning Bird", "channel": "Beyond3Baje", "createdAt": "2026-09-22T19:00:00Z"},
        {"id": "d1", "title": "Inkanyamba: Waterfall Serpent", "channel": "Beyond3Baje", "createdAt": "2026-09-22T18:00:00Z"},
    ]), encoding="utf-8")

    ran = []

    class FakeEngine:
        def execute_next(self, project_id, allow_all=None):
            p = Project.load(project_id)
            ran.append((p.brand, p.current_step, allow_all))
            steps = {"after_dark_narration": ["Account Collection", "Script Writing", "Visual Plan"],
                     "beyond3baje_documentary": ["Research", "Scripting", "Visual Plan"],
                     "life3baje_video": ["Vlog Planning", "Vlog Script & Prompts", "Visual Plan"]}[p.workflow_name]
            # Like the real engine: an unknown current step means the first one.
            at = steps.index(p.current_step) if p.current_step in steps else 0
            p.current_step = steps[at + 1]
            p.save()
            return p

    monkeypatch.setattr("runtime.workflow.WorkflowEngine", FakeEngine)
    return tmp_path, ran, cfg


def test_without_a_strategist_it_falls_back_to_the_best_vault_topic_then_the_idea_dump(sandbox, monkeypatch):
    tmp_path, ran, _ = sandbox
    monkeypatch.setattr(longform_nightly, "plan", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no model")))
    record = longform_nightly.run()

    by_channel = {b["channel"]: b for b in record["built"]}
    assert by_channel["Raat3Baje"]["title"] == "Kuldhara Ki Raat"
    assert by_channel["Beyond3Baje"]["title"] == "Inkanyamba: Waterfall Serpent"   # oldest Idea Dump idea
    assert all(b["current_step"] == "Visual Plan" for b in record["built"])
    assert all(allow for _, _, allow in ran) and len(ran) == 6

    stages = {t["topic"]: t["stage"] for t in topic_store.load_topics()}
    assert stages["Kuldhara Ki Raat"] == "in_progress" and stages["Low ghost"] == "backlog"
    assert stages["Inkanyamba: Waterfall Serpent"] == "in_progress"               # promoted from the dump

    from core.models.project import Project
    p = Project.load(by_channel["Raat3Baje"]["project_id"])
    assert p.metadata["allow_all"] is False and p.metadata["target_duration_minutes"] == 8
    assert longform_nightly.settings()["last_run"] == record["last_run"]

    status = longform_nightly.read_status()
    assert status["state"] == "done" and status["trigger"] == "nightly"
    assert [t["stage"] for t in status["tasks"]] == ["done", "done", "done"]
    assert any("strategist could not plan" in line["text"] for line in status["log"])


def test_the_strategists_plan_and_the_creators_instructions_reach_the_project(sandbox, monkeypatch):
    tmp_path, _, cfg = sandbox
    cfg.update(longform_nightly_channels=["Beyond3Baje"], longform_nightly_minutes={"Beyond3Baje": 15},
               longform_nightly_instructions={"Beyond3Baje": "Only African myths. Open cold, no intro."})
    seen = {}

    def fake_run(agent, channel, task, system_extra="", on_event=None, **_):
        seen.update(agent=agent, task=task)
        on_event("web search: Impundulu folklore")
        return {"plan": {"topic_ref": "dump:d2", "title": "Impundulu: Bijli Wala Pakshi",
                         "angle": "the bird that brings lightning", "brief": "## Hook\nStorm night."},
                "turns": 2, "calls": ["web search: Impundulu folklore"]}

    monkeypatch.setattr(strategist_runner, "run", fake_run)
    built = longform_nightly.run(trigger="manual")["built"][0]

    assert seen["agent"] == "Beyond3BajeStrategist"
    assert "Only African myths. Open cold, no intro." in seen["task"]
    assert "[dump:d1] Inkanyamba: Waterfall Serpent" in seen["task"]

    from core.models.project import Project
    p = Project.load(built["project_id"])
    assert p.name == "Impundulu: Bijli Wala Pakshi"
    assert p.metadata["creator_instructions"] == "Only African myths. Open cold, no intro."
    assert "the bird that brings lightning" in p.metadata["creative_brief"]
    assert p.metadata["target_duration_minutes"] == 15
    assert p.assets["strategist_brief"] == "script/strategist_brief.md"
    assert [(t["topic"], t["stage"]) for t in topic_store.load_topics() if t["channel"] == "Beyond3Baje"] == \
        [("Impundulu: Lightning Bird", "in_progress")]
    log = [line["text"] for line in longform_nightly.read_status()["log"]]
    assert "web search: Impundulu folklore" in log


def test_strategist_loop_runs_tools_feeds_results_back_and_refuses_unsafe_ones(sandbox, monkeypatch):
    replies = iter([
        "Let me look. [IDEA_DUMP: Beyond3Baje] [STUDIO_ACTION: settings_get] [SWITCH_MODEL: other-model]",
        '[FINAL_PLAN]{"topic_ref": "dump:d1", "title": "T", "brief": "B"}[/FINAL_PLAN]',
    ])
    conversations = []

    class FakeLLM:
        last_response_simulated = False

    class FakeAgent:
        llm_service = FakeLLM()

        def execute_messages(self, messages, system_extra=""):
            conversations.append([dict(m) for m in messages])
            assert "[INVOKE_AGENT: AgentName]" in system_extra and "topic_save" in system_extra
            assert "settings_get" not in system_extra
            return next(replies)

    monkeypatch.setattr("core.agent.AgentFactory.get_agent", lambda name, llm=None: FakeAgent())
    events = []
    out = strategist_runner.run("Beyond3BajeStrategist", "Beyond3Baje", "plan one", on_event=events.append,
                                llm=FakeLLM())

    assert out["plan"]["topic_ref"] == "dump:d1" and out["turns"] == 2
    results = conversations[1][-1]["content"]
    assert "[dump:d1] Inkanyamba: Waterfall Serpent" in results           # the tool's answer came back
    assert "'settings_get' is not available unattended" in results
    assert "SWITCH_MODEL is not available unattended" in results
    assert [m["role"] for m in conversations[1]] == ["user", "assistant", "user"]
    assert "idea dump: Beyond3Baje" in events


def test_longform_api_saves_settings_and_instructions(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    saved = {}
    monkeypatch.setattr("integrations.llm.load_config", lambda: dict(saved))
    monkeypatch.setattr("integrations.llm.save_config", lambda c: saved.update(c))
    c = TestClient(app)
    state = c.get("/api/longform/nightly").json()
    assert state["channels"] == ["Raat3Baje", "Beyond3Baje", "Life3Baje"]
    assert state["minutes"] == {"Raat3Baje": 8.0, "Beyond3Baje": 8.0, "Life3Baje": 8.0}
    assert state["strategists"]["Raat3Baje"] == "AfterDarkStrategist" and "status" in state
    state = c.post("/api/longform/nightly", json={"channels": ["Life3Baje"], "per_channel": 9,
                                                   "minutes": {"Raat3Baje": 20, "Life3Baje": 0},
                                                   "instructions": {"Life3Baje": "Honest numbers."}}).json()
    assert state["channels"] == ["Life3Baje"] and state["per_channel"] == 5
    assert state["minutes"] == {"Raat3Baje": 20.0, "Beyond3Baje": 8.0, "Life3Baje": 1.0}
    assert state["instructions"]["Life3Baje"] == "Honest numbers." and state["instructions"]["Raat3Baje"] == ""
    assert c.post("/api/longform/nightly", json={"channels": ["Khayal3Baje"]}).status_code == 400
    saved["longform_nightly_minutes"] = 10                                 # an old single number
    assert c.get("/api/longform/nightly").json()["minutes"]["Beyond3Baje"] == 10.0


def test_longform_has_its_own_schedule_and_windows_task(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from integrations import nightly_task
    saved = {"nightly_time": "03:00", "nightly_hibernate": False}
    calls = []
    monkeypatch.setattr("integrations.llm.load_config", lambda: dict(saved))
    monkeypatch.setattr("integrations.llm.save_config", lambda c: saved.update(c))
    monkeypatch.setattr(nightly_task, "register", lambda hhmm, scope="shorts": calls.append(("register", hhmm, scope)) or {})
    monkeypatch.setattr(nightly_task, "unregister", lambda scope="shorts": calls.append(("unregister", scope)) or {})
    c = TestClient(app)
    assert c.get("/api/longform/nightly").json()["schedule"]["time"] == "03:00"    # until it has a time of its own
    state = c.post("/api/longform/nightly", json={"time": "5:30", "hibernate": False, "idle_minutes": 500}).json()
    assert state["schedule"]["time"] == "05:30" and state["schedule"]["hibernate"] is False
    assert state["schedule"]["idle_minutes"] == 120
    assert saved["longform_time"] == "05:30" and saved["nightly_time"] == "03:00" and saved["nightly_hibernate"] is False
    assert calls == [("register", "05:30", "longform")]
    c.post("/api/longform/nightly", json={"enabled": False})
    assert calls[-1] == ("unregister", "longform")
    assert c.post("/api/longform/nightly", json={"time": "25:00"}).status_code == 400
    c.post("/api/longform/nightly", json={"per_channel": 2})                           # no task change
    assert len(calls) == 2


def test_each_windows_task_runs_only_its_own_scheduler():
    from integrations import nightly_task
    assert nightly_task.TASK_NAMES["shorts"] != nightly_task.TASK_NAMES["longform"]
    assert "--only shorts" in nightly_task._task_xml("03:00", "shorts")
    xml = nightly_task._task_xml("04:30", "longform")
    assert "--only longform" in xml and "T04:30:00" in xml


def test_strategists_get_the_whole_channel_guide_and_other_agents_the_excerpt():
    from app.services import studio_chat
    full = studio_chat.channel_guide("Beyond3Baje", full=True)
    assert "## Initial topic pool" in full and len(full) > studio_chat.GUIDE_CHARS
    assert "## Initial topic pool" in studio_chat.build_system_extra("Beyond3BajeStrategist", "Beyond3Baje", "hi", None)
    assert "## Initial topic pool" not in studio_chat.build_system_extra("ResearchAgent", "Beyond3Baje", "hi", None)


def test_raat3baje_alternates_rules_and_fictional_story_episodes(sandbox, monkeypatch):
    tmp_path, _, cfg = sandbox
    cfg.update(longform_nightly_channels=["Raat3Baje"], longform_nightly_per_channel=3,
               longform_nightly_instructions={"Raat3Baje": "Pure story."})
    tasks = []

    def fake_run(agent, channel, task, system_extra="", on_event=None, **_):
        tasks.append(task)
        return {"plan": {"topic_ref": "new", "title": f"Episode {len(tasks)}", "brief": "b"}, "turns": 1, "calls": []}

    monkeypatch.setattr(strategist_runner, "run", fake_run)
    first = longform_nightly.run(trigger="manual")["built"]
    assert [b["format"] for b in first] == ["rules", "story", "rules"]
    assert "'RULES' HORROR" in tasks[0] and "FICTIONAL HORROR STORY" in tasks[1]

    from core.models.project import Project
    p = Project.load(first[1]["project_id"])
    assert p.metadata["episode_format"] == "story"
    assert p.metadata["creator_instructions"].startswith("Pure story.")
    assert "FICTIONAL HORROR STORY" in p.metadata["creator_instructions"]

    # The next run carries on from the last episode built.
    cfg["longform_nightly_per_channel"] = 1
    assert [b["format"] for b in longform_nightly.run(trigger="manual")["built"]] == ["story"]
