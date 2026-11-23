"""Shorts Desk (app/services/shorts_desk.py) with the web, Kavita Kosh, YouTube
and every model faked -- no network, no LLM."""
import json
import os

import pytest

from app.services import poetry_sources, shorts_desk


def _poem(title, poet, text):
    return {"source": "Kavita Kosh", "title": title, "poet": poet, "text": text, "glosses": ["arth"],
            "categories": [], "url": f"https://kavitakosh.org/kk/{title}", "lines": text.count("\n") + 1}


GHAZAL = "न था कुछ तो ख़ुदा था\nडुबोया मुझको होने ने\n\nहुआ जब ग़म से यूँ बेहिस\nन होता गर जुदा तन से"


@pytest.fixture
def faked(monkeypatch, tmp_path):
    monkeypatch.setattr(shorts_desk, "STORE_DIR", str(tmp_path / "desk"))
    monkeypatch.setattr(shorts_desk, "_web", lambda queries, per_query=8, news_query=None: [
        {"title": "Top sher", "snippet": "ग़ालिब", "url": "https://example.com/a", "source": "t"}])
    pages = {
        "ग़ज़ल एक / ग़ालिब": _poem("ग़ज़ल एक", "ग़ालिब", GHAZAL),
        "वही ग़ज़ल दूसरा नाम / ग़ालिब": _poem("वही ग़ज़ल दूसरा नाम", "ग़ालिब", GHAZAL),
        "ग़ालिब पर कविता / कोई और": _poem("ग़ालिब पर कविता", "कोई और", "चचा ग़ालिब की\nनींद"),
    }
    monkeypatch.setattr(shorts_desk, "_poet_works", lambda poet, limit: list(pages))
    monkeypatch.setattr(poetry_sources, "search_kavitakosh", lambda q, limit=10: [])
    monkeypatch.setattr(poetry_sources, "fetch_poem", lambda title: pages.get(title))
    monkeypatch.setattr(poetry_sources, "poet_info", lambda p: {"rights": "public_domain", "died": 1869,
                                                                "public_domain_from": 1930})
    monkeypatch.setattr(shorts_desk, "_evidence", lambda c, f: {"median_short_views": 1000, "max_short_views": 5000,
                                                                "near_duplicates": 0, "top": [], "results": 3})
    calls = []

    def agent(name, task):
        calls.append((name, task))
        if task.get("task") == "plan":
            return {"poets": [], "lines": []}
        if task.get("task") == "select":
            return {"candidates": [{"id": item["id"], "title": "working", "hook": "h"} for item in task["pool"]]}
        if name == "ViralityJudge":
            return {"scores": [{"id": c["id"], "score": 80, "verdict": "make", "reasons": ["r"]} for c in task["candidates"]]}
        return {"title": "शीर्षक", "title_en": "Ghalib Khuda Tha", "intro": "suniye", "outro": "yaad rakhiye",
                "caption": "cap", "hashtags": ["#ghalib"], "meaning_note": "m", "script": ""}

    monkeypatch.setattr(shorts_desk, "_agent_json", agent)
    return calls


def test_poem_find_keeps_the_poets_own_work_once(faked):
    result = shorts_desk.find("Life3Baje", "shayari", {"poet": "ग़ालिब"}, count=5)
    titles = [c["title"] for c in result["candidates"]]
    assert titles == ["ग़ज़ल एक"]            # duplicate page and the poem *about* Ghalib are gone
    cand = result["candidates"][0]
    assert cand["text"].startswith("न था कुछ") and cand["rights"] == "public_domain"
    assert cand["working_title"] == "working"  # the scout's title never replaces the real one
    # The scout only ever saw fetched material, never a request to recall poems.
    select = next(task for name, task in faked if task.get("task") == "select")
    assert all(item["opening"] for item in select["pool"])


def test_build_inserts_the_poem_verbatim_and_makes_a_short_project(faked, monkeypatch, tmp_path):
    from executive.project import project_manager
    monkeypatch.setattr(project_manager, "projects_dir", str(tmp_path / "projects"))
    monkeypatch.setattr("core.models.project._project_dir_for", lambda pid: str(tmp_path / "projects" / pid))
    cand = shorts_desk.find("Life3Baje", "shayari", {"poet": "ग़ालिब"}, count=1)["candidates"][0]
    project = shorts_desk.build("Life3Baje", "shayari", cand)
    assert project["id"].endswith("_Life3Baje_ShortGhalibKhudaTha")
    pdir = tmp_path / "projects" / project["id"]
    script = (pdir / "script" / "short_script.md").read_text(encoding="utf-8")
    assert "न था कुछ तो ख़ुदा था\nडुबोया मुझको होने ने\n\n(pause)\n\nहुआ जब ग़म से यूँ बेहिस" in script
    assert project["assets"]["script"] == "script/short_script.md"
    assert project["metadata"]["video_settings"]["shorts_clips"] == 0
    assert project["metadata"]["short_format"] == "shayari"
    assert project["steps_history"][0]["status"] == "completed"
    package = json.loads((pdir / "publish" / "short_package.json").read_text(encoding="utf-8"))
    assert package["hashtags"] == ["#ghalib"] and package["rights"] == "public_domain"


def test_narrated_reel_over_budget_script_is_rewritten_once_and_the_shorter_wins(monkeypatch, tmp_path):
    """REELS_DESK_PLAN.md VR9 (creator follow-up 2026-10-24): the length pick is a
    target, not a cap -- a script well past REWRITE_LENGTH_FACTOR x it gets one
    rewrite-to-length call, and the shorter of the two scripts is kept."""
    from executive.project import project_manager

    monkeypatch.setattr(shorts_desk, "STORE_DIR", str(tmp_path / "desk"))
    monkeypatch.setattr(project_manager, "projects_dir", str(tmp_path / "projects"))
    monkeypatch.setattr("core.models.project._project_dir_for", lambda pid: str(tmp_path / "projects" / pid))

    long_script = " ".join(["ek"] * 300)    # 300 spoken words: well past 124 * 1.5 = 186
    short_script = " ".join(["ek"] * 110)   # back inside the target
    calls = []

    def agent(name, task):
        calls.append((name, task))
        if "previous_script" in task:
            return {"title": "Raat ke niyam", "script": short_script}
        return {"title": "Raat ke niyam", "script": long_script}

    monkeypatch.setattr(shorts_desk, "_agent_json", agent)
    cand = {"title": "Raat ke niyam", "filters": {"length": "1 minute (60 seconds)"}}
    project = shorts_desk.build("Raat3Baje", "rules_horror", cand)

    assert len(calls) == 2
    assert "about 135 spoken words (60-90 s is fine)" in calls[0][1]["target_length"]
    assert calls[1][1]["previous_script"] == long_script and calls[1][1]["rewrite_to_words"] == 135

    pdir = tmp_path / "projects" / project["id"]
    script = (pdir / "script" / "short_script.md").read_text(encoding="utf-8")
    assert short_script in script and long_script not in script

    wb = project["metadata"]["word_budget"]
    assert wb["budget"] == 135 and wb["written"] == 300 and wb["rewritten"] == 110 and wb["final"] == 110
    logs = project["steps_history"][0]["logs"]
    assert any("Word budget 135" in l and "kept 110" in l for l in logs)


def test_over_budget_script_keeps_the_original_when_the_rewrite_is_not_shorter(monkeypatch, tmp_path):
    from executive.project import project_manager

    monkeypatch.setattr(shorts_desk, "STORE_DIR", str(tmp_path / "desk"))
    monkeypatch.setattr(project_manager, "projects_dir", str(tmp_path / "projects"))
    monkeypatch.setattr("core.models.project._project_dir_for", lambda pid: str(tmp_path / "projects" / pid))

    long_script = " ".join(["ek"] * 300)
    still_long_script = " ".join(["ek"] * 280)   # the rewrite barely trims it: still over budget

    def agent(name, task):
        if "previous_script" in task:
            return {"title": "Raat ke niyam", "script": still_long_script}
        return {"title": "Raat ke niyam", "script": long_script}

    monkeypatch.setattr(shorts_desk, "_agent_json", agent)
    cand = {"title": "Raat ke niyam", "filters": {"length": "1 minute (60 seconds)"}}
    project = shorts_desk.build("Raat3Baje", "rules_horror", cand)

    pdir = tmp_path / "projects" / project["id"]
    script = (pdir / "script" / "short_script.md").read_text(encoding="utf-8")
    # The rewrite did shorten it (280 < 300), so it still wins over the first draft.
    assert still_long_script in script and long_script not in script
    assert project["metadata"]["word_budget"]["final"] == 280


def test_a_script_inside_the_fine_range_is_never_rewritten(monkeypatch, tmp_path):
    """2026-10-24 creator follow-up: the length is a target, not a cap -- a script
    under REWRITE_LENGTH_FACTOR (1.5) x the budget (186 words for a 60 s/124-word
    target) is kept as written, even though it runs past the target itself."""
    from executive.project import project_manager

    monkeypatch.setattr(shorts_desk, "STORE_DIR", str(tmp_path / "desk"))
    monkeypatch.setattr(project_manager, "projects_dir", str(tmp_path / "projects"))
    monkeypatch.setattr("core.models.project._project_dir_for", lambda pid: str(tmp_path / "projects" / pid))

    fine_script = " ".join(["ek"] * 180)   # over the 124-word target, still under 186
    calls = []

    def agent(name, task):
        calls.append((name, task))
        return {"title": "Raat ke niyam", "script": fine_script}

    monkeypatch.setattr(shorts_desk, "_agent_json", agent)
    cand = {"title": "Raat ke niyam", "filters": {"length": "1 minute (60 seconds)"}}
    project = shorts_desk.build("Raat3Baje", "rules_horror", cand)

    assert len(calls) == 1   # no rewrite call
    wb = project["metadata"]["word_budget"]
    assert wb == {"budget": 135, "written": 180, "final": 180}


def test_a_poem_or_a_length_with_no_seconds_gets_no_word_budget(faked, monkeypatch, tmp_path):
    from executive.project import project_manager

    monkeypatch.setattr(project_manager, "projects_dir", str(tmp_path / "projects"))
    monkeypatch.setattr("core.models.project._project_dir_for", lambda pid: str(tmp_path / "projects" / pid))
    cand = shorts_desk.find("Life3Baje", "shayari", {"poet": "ग़ालिब"}, count=1)["candidates"][0]
    project = shorts_desk.build("Life3Baje", "shayari", cand)
    assert "word_budget" not in project["metadata"]


def test_a_story_without_a_readable_source_is_dropped(faked, monkeypatch):
    monkeypatch.setattr(shorts_desk, "_story_pool", lambda fmt_key, fmt, filters, say: [
        {"title": "NH-17", "snippet": "s", "url": "https://blog.example/nh17", "source": "t"},
        {"title": "Stub", "snippet": "s", "url": "https://stub.example/x", "source": "t"}])
    monkeypatch.setattr(shorts_desk, "_fetch_note", lambda r: (
        {"title": r["title"], "url": r["url"], "snippet": "", "text": "x" * 800} if "blog" in r["url"] else None))
    monkeypatch.setattr("app.services.web_research.search_web", lambda q, max_results=6: [])
    result = shorts_desk.find("Raat3Baje", "horror_incident", {}, count=5)
    assert [c["title"] for c in result["candidates"]] == ["working"]
    assert result["candidates"][0]["notes"][0]["url"] == "https://blog.example/nh17"


def test_excerpt_ends_on_a_whole_couplet():
    text = "a\nb\n\nc\nd\n\ne\nf"
    assert poetry_sources.excerpt(text, 4) == "a\nb\n\nc\nd"
    assert poetry_sources.excerpt(text, 5) == "a\nb\n\nc\nd"


def test_original_fiction_survives_thin_sources_and_is_labelled(faked, monkeypatch):
    monkeypatch.setattr(shorts_desk, "_story_pool", lambda fmt_key, fmt, filters, say: [
        {"title": "Haveli rules", "snippet": "s", "url": "https://stub.example/x", "source": "t"}])
    monkeypatch.setattr(shorts_desk, "_fetch_note", lambda r: None)
    monkeypatch.setattr("app.services.web_research.search_web", lambda q, max_results=6: [])
    result = shorts_desk.find("Raat3Baje", "rules_horror", {"setting": "Haveli"}, count=3)
    assert [c["rights"] for c in result["candidates"]] == ["original fiction"]


def test_beyond3baje_formats_are_international_and_raat3baje_indian():
    assert set(shorts_desk.FORMATS["Beyond3Baje"]) == {"entity", "encounter", "case_file", "haunted_location",
                                                       "urban_legend", "unsolved", "what_if", "anomaly_file"}
    for key, fmt in shorts_desk.FORMATS["Beyond3Baje"].items():
        # The What If stories and the Anomaly Files (2026-10-23) happen in the
        # viewer's own Indian setting; the investigations stay outside India.
        if key in ("what_if", "anomaly_file"):
            assert fmt["writer"] == "WhatIfWriter" and fmt["kind"] == "fiction"
            assert any(f["key"] == "length" for f in fmt["filters"]), "the length is the creator's pick"
            continue
        assert "India" not in " ".join(fmt["queries"])
    assert all("India" in " ".join(f["queries"]) or "लोककथा" in " ".join(f["queries"]) or "रात" in " ".join(f["queries"])
               for f in shorts_desk.FORMATS["Raat3Baje"].values())


def test_in_app_schedule_defers_to_the_nightly_run(monkeypatch, tmp_path):
    from datetime import datetime
    monkeypatch.setattr(shorts_desk, "STORE_DIR", str(tmp_path / "desk"))
    monkeypatch.setattr(shorts_desk, "NIGHTLY_LOCK", str(tmp_path / "running.lock"))
    cfg = {"shorts_daily_enabled": True, "shorts_daily_time": "07:00", "nightly_enabled": True, "nightly_time": "03:00"}
    monkeypatch.setattr("integrations.llm.load_config", lambda: cfg)
    assert not shorts_desk._daily_due(datetime(2026, 9, 29, 3, 30))    # the nightly run owns 03:00
    assert shorts_desk._daily_due(datetime(2026, 9, 29, 7, 30))        # fallback 4 h later, no run yet
    (tmp_path / "running.lock").write_text("1")
    assert not shorts_desk._daily_due(datetime(2026, 9, 29, 7, 30))    # never while nightly holds its lock
    cfg["nightly_enabled"] = False
    (tmp_path / "running.lock").unlink()
    assert not shorts_desk._daily_due(datetime(2026, 9, 29, 6, 59))
    assert shorts_desk._daily_due(datetime(2026, 9, 29, 7, 0))


def test_nightly_task_first_run_skips_a_time_too_close(monkeypatch):
    import datetime as dt
    from integrations import nightly_task

    class FakeNow(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 28, 2, 11)

    monkeypatch.setattr(dt, "datetime", FakeNow)
    assert nightly_task._first_day("03:00") == "2026-09-29"
    assert nightly_task._first_day("08:00") == "2026-09-28"
    xml = nightly_task._task_xml("03:00")
    assert "<WakeToRun>true</WakeToRun>" in xml and "2026-09-29T03:00:00" in xml


def test_agent_json_repairs_local_model_slips_and_strips_half_emoji():
    raw = '```json\n{"title": "X", "hashtags": [#Ghost, "#Real", #Haunted,], "script": "a",}\n```'
    assert shorts_desk._parse_json(raw) == {"title": "X", "hashtags": ["#Ghost", "#Real", "#Haunted"], "script": "a"}
    assert shorts_desk._clean_text({"t": ["ok \ud83d end"]}) == {"t": ["ok  end"]}
    assert shorts_desk._parse_json("no json here") is None


# --- the judge's reply is read in whatever shape a local model gives it ------------------

@pytest.mark.parametrize("judged", [
    {"scores": [{"id": "c4", "score": 90}]},
    {"id": "c4", "score": 90, "verdict": "strong"},
    [{"id": "c4", "score": 90}],
    {"candidates": [{"id": "c4", "score": 90}]},
    {"results": {"c4": {"score": 90}}},
    {"c4": {"score": 90}, "c1": {"score": 40}},
])
def test_score_list_reads_every_shape_a_small_model_answers_in(judged):
    scores = {s["id"]: s for s in shorts_desk._score_list(judged)}
    assert scores["c4"]["score"] == 90


def test_score_list_is_empty_for_prose_or_nothing():
    assert shorts_desk._score_list(None) == []
    assert shorts_desk._score_list({"analysis": {"overall": "too generic"}}) == []
