"""Recording sessions (the Shorts first, then the long video), the face-first
layout and the research-first SEO step (2026-10-16)."""
import json
import os

import pytest

from app.services import session_format, session_split
from integrations import story_visuals


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    """Settings are a dict here: nothing reads or writes the real config.json."""
    cfg = {}
    monkeypatch.setattr("integrations.llm.load_config", lambda: cfg)
    monkeypatch.setattr("integrations.llm.save_config", lambda c: cfg.update(c))
    return cfg


@pytest.fixture
def projects(monkeypatch, tmp_path):
    from executive.project import project_manager
    monkeypatch.setattr(project_manager, "projects_dir", str(tmp_path / "projects"))
    monkeypatch.setattr("core.models.project._project_dir_for", lambda pid: str(tmp_path / "projects" / pid))
    return tmp_path


def _project(brand="Raat3Baje", workflow="after_dark_narration", name="Masaan Ki Raat", **meta):
    from executive.project import project_manager
    p = project_manager.create_project(name=name, brand=brand, workflow_name=workflow)
    p.metadata.update(meta)
    p.save()
    return p


# --- channel defaults and the project's own choice ------------------------------------

def test_the_three_session_channels_record_shorts_first_by_default(projects, _config):
    assert session_format.is_shorts_first(_project())
    assert session_format.is_shorts_first(_project(brand="Life3Baje", workflow="life3baje_video", name="Life one"))
    assert not session_format.is_shorts_first(_project(brand="Khayal3Baje", workflow="khayal3baje_horror", name="K one"))
    # A project's own choice wins; a Short never is one.
    assert not session_format.is_shorts_first(_project(name="Long only", session_format="long_only"))
    assert not session_format.is_shorts_first(_project(name="A short", workflow="shorts_ready"))
    # The channel's default is saved in the settings.
    session_format.set_channel_defaults("Raat3Baje", {"shorts_first": False, "shorts_count": 9,
                                                      "face_layout": "face_intro", "face_intro_seconds": 500})
    saved = _config["channel_formats"]["Raat3Baje"]
    assert saved == {"shorts_first": False, "shorts_count": 4, "face_layout": "face_intro", "face_intro_seconds": 180}
    assert not session_format.is_shorts_first(_project(name="After the change"))
    assert session_format.shorts_count(_project(name="Count", session_shorts_count=3)) == 3


def test_the_shorts_reply_is_parsed_and_a_greeting_is_taken_out():
    raw = "```json\n" + json.dumps({"shorts": [
        {"title": "Rule No. 7", "script": "Hello doston, mera naam hai Sudhansu aur aap dekh rahe hain Raat 3 Baje. "
                                          "Raat ke teen baje darwaza teen baar khatka.", "hashtags": ["horror"]},
        {"title": "", "script": ""},
        {"title": "Masaan", "script": "Shamshan mein ek diya hamesha jalta hai.", "estimated_seconds": 55},
    ]}) + "\n```"
    shorts = session_format.parse_shorts(raw)
    assert [s["title"] for s in shorts] == ["Rule No. 7", "Masaan"]
    assert shorts[0]["hashtags"][0] == "#shorts" and "#horror" in shorts[0]["hashtags"]
    assert shorts[1]["estimated_seconds"] == 55
    cleaned = session_format.strip_greeting(shorts[0]["script"])
    assert "Sudhansu" not in cleaned and cleaned.startswith("Raat ke teen baje")
    assert session_format.parse_shorts("no json here") == []


def test_the_recording_script_is_the_shorts_then_the_long_video(projects):
    p = _project()
    with open(os.path.join(p.get_project_dir(), "script", "draft.md"), "w", encoding="utf-8") as f:
        f.write("# Masaan Ki Raat\n\nHello doston, mera naam hai Sudhansu. Kahani shuru hoti hai...\n")
    p.assets["script"] = "script/draft.md"
    session_format.save_shorts(p, [{"title": "One", "script": "Pehla short."}, {"title": "Two", "script": "Doosra short."}])
    rel = session_format.refresh_recording_script(p)
    assert rel == session_format.RECORDING_SCRIPT and p.assets["recording_script"] == rel
    text = open(os.path.join(p.get_project_dir(), rel), encoding="utf-8").read()
    assert text.index("Pehla short.") < text.index("Doosra short.") < text.index("Hello doston")
    assert "SHORT 1 of 2 -- One" in text and "(pause 3s)" in text
    # A long-only project has no recording script.
    p.metadata["session_format"] = "long_only"
    assert session_format.refresh_recording_script(p) is None


def test_a_sessions_long_script_opens_on_the_greeting(projects):
    from app.services.writing_style import greeting
    line = greeting("Raat3Baje")
    script = f"# Masaan Ki Raat\n\nRaat ke teen baje darwaza khatka.\n\n{line} Aaj ki kahani...\n\nBaaki kahani.\n"
    moved, changed = session_format.greeting_first(script, "Raat3Baje")
    assert changed and moved.startswith(f"# Masaan Ki Raat\n\n{line}")
    assert moved.index("Raat ke teen baje") > moved.index(line) and moved.count(line) == 1
    assert session_format.greeting_first(moved, "Raat3Baje") == (moved, False)
    assert "very FIRST line" in session_format.long_script_direction(_project())
    assert session_format.long_script_direction(_project(name="Solo", session_format="long_only")) == ""


# --- the workflow step ---------------------------------------------------------------

class _LLM:
    config: dict = {}
    last_response_simulated = False


class _Agent:
    model_tier = "premium"

    def __init__(self, reply):
        self.reply = reply
        self.tasks = []
        self.llm_service = _LLM()

    def execute(self, task, require_json=False):
        self.tasks.append(task)
        return self.reply


def test_the_shorts_step_runs_for_a_session_and_is_skipped_otherwise(projects, monkeypatch):
    from app.services import writing_style
    from runtime.workflow import WorkflowEngine
    monkeypatch.setattr(writing_style, "style_section", lambda brand, project=None: "")
    reply = json.dumps({"shorts": [{"title": f"S{k}", "script": f"Short number {k} ki kahani."} for k in range(1, 4)]})
    agent = _Agent(reply)
    engine = WorkflowEngine(llm_service=_LLM())
    monkeypatch.setattr(engine, "_resolve_agent", lambda role: agent)

    p = _project(allow_all=True)
    with open(os.path.join(p.get_project_dir(), "script", "draft.md"), "w", encoding="utf-8") as f:
        f.write("Hello doston. The long story.\n")
    p.assets["script"] = "script/draft.md"
    p.current_step = "Shorts Scripts"
    p.save()
    p = engine.execute_next(p.id)
    assert p.current_step == "Visual Plan"
    assert "the session's 3 Shorts" in agent.tasks[0] and "NO greeting" in agent.tasks[0]
    assert [s["title"] for s in session_format.load_shorts(p)] == ["S1", "S2", "S3"]
    assert p.assets["shorts_set"] == session_format.SHORTS_MD and p.assets["recording_script"]

    q = _project(name="Long only", session_format="long_only", allow_all=True)
    q.current_step = "Shorts Scripts"
    q.save()
    q = engine.execute_next(q.id)
    assert q.current_step == "Visual Plan" and len(agent.tasks) == 1
    assert q.steps_history[-1].logs[0].startswith("Skipped:")


# --- splitting the recording -----------------------------------------------------------

def _words(text, start=0.0, gap_after=None):
    out, t = [], start
    for k, w in enumerate(text.split()):
        out.append({"word": w, "start": round(t, 2), "end": round(t + 0.3, 2), "tl_start": None, "tl_end": None})
        t += 0.4 + (gap_after.get(k, 0.0) if gap_after else 0.0)
    return out, t


def _session_words():
    s1, t = _words("Raat ke teen baje darwaza teen baar khatka aur phir koi andar aaya " * 3, 0.0)
    s2, t = _words("Shamshan mein ek diya hamesha jalta hai kehte hain wahan koi rehta hai " * 3, t + 4.0)
    long_, _ = _words("Hello dosto mera naam hai Sudhanshu aur aap dekh rahe hain Raat 3 Baje aaj ki kahani " * 2, t + 5.0)
    words = s1 + s2 + long_
    for k, w in enumerate(words):  # the programme: the edit closes the silences
        w["tl_start"] = round(k * 0.4, 2)
        w["tl_end"] = round(k * 0.4 + 0.3, 2)
    return words, len(s1), len(s1) + len(s2)


def test_the_long_video_starts_at_the_greeting_even_misheard():
    words, _, long_at = _session_words()
    greeting = "Hello doston, mera naam hai Sudhansu aur aap dekh rahe hain Raat 3 Baje."
    assert session_split.find_greeting(words, greeting) == long_at
    assert session_split.find_long_start(words, greeting) == (long_at, "greeting")
    assert session_split.find_long_start(words, greeting, manual_s=words[5]["start"]) == (5, "manual")
    assert session_split.find_greeting(words[:long_at], greeting) is None


def test_a_shorts_own_words_are_not_the_greeting():
    greeting = "Hello doston, mera naam hai Sudhansu aur aap dekh rahe hain Raat 3 Baje."
    scary, t = _words("Raat ke 3 baje mera naam kisi ne pukara maine dekha woh log dekh rahe the uska naam")
    assert session_split.find_greeting(scary, greeting) is None
    # The Short ends on a greeting word ("naam"), a pause, then the greeting: it starts at "Hello".
    long_, _ = _words("Hello dosto mera naam hai Sudhanshu aur aap dekh rahe hain Raat 3 Baje", t + 3.0)
    assert session_split.find_greeting(scary + long_, greeting) == len(scary)


def test_the_shorts_are_found_by_their_openings_or_the_silences():
    words, second, long_at = _session_words()
    scripts = ["Raat ke teen baje darwaza teen baar khatka", "Shamshan mein ek diya hamesha jalta hai"]
    assert session_split.plan_shorts(words, long_at, scripts, 2) == [(0, 0, second - 1), (1, second, long_at - 1)]
    # Without scripts: the longest silence.
    assert session_split.plan_shorts(words, long_at, [], 2) == [(0, 0, second - 1), (1, second, long_at - 1)]


class _Client:
    def __init__(self, words):
        self.words = words
        self.cuts = []

    def get_kept_words(self, project_id):
        if not self.cuts:
            return [dict(w) for w in self.words]
        # After the cut: the words inside it are struck (BuzzEdit's cut_program_range).
        end_frame = self.cuts[-1][1]
        return [dict(w) for w in self.words if w["tl_start"] * 30 >= end_frame]

    def get_project(self, project_id):
        return {"timeline": {"fps_num": 30, "fps_den": 1}}

    def cut_program(self, project_id, start_frame, end_frame):
        self.cuts.append((start_frame, end_frame))
        return {"status": "success"}


def test_a_session_becomes_its_shorts_and_the_long_video(projects, monkeypatch, tmp_path):
    words, second, long_at = _session_words()
    recording = tmp_path / "take.mp4"
    recording.write_bytes(b"video")
    cut_out = []
    monkeypatch.setattr(session_split, "extract_clip",
                        lambda rec, a, b, out: cut_out.append((a, b)) or open(out, "wb").close() or out)
    p = _project(buzzedit_project_id="be1", recording_path=str(recording))
    session_format.save_shorts(p, [{"title": "Darwaza", "script": "Raat ke teen baje darwaza teen baar khatka"},
                                   {"title": "Diya", "script": "Shamshan mein ek diya hamesha jalta hai"}])
    p.save()
    client = _Client(words)
    record = session_split.split(p, client)
    assert record["how"] == "greeting" and record["boundary_s"] == words[long_at]["start"]
    assert [s["title"] for s in record["shorts"]] == ["Darwaza", "Diya"]
    assert len(cut_out) == 2 and cut_out[0][0] == 0.0 and cut_out[1][1] <= words[long_at]["start"]
    assert client.cuts == [(0, round((words[long_at]["tl_start"] - session_split.CUT_LEAD_S) * 30))]

    from core.models.project import Project
    child = Project.load(record["shorts"][1]["project_id"])
    assert child.workflow_name == "shorts_ready" and child.name == "Diya"
    assert child.metadata["session_parent"]["project_id"] == p.id
    assert child.metadata["video_settings"]["shorts_full"] is True
    assert child.metadata["recording_path"].endswith("take_short2.mp4")
    assert not session_format.is_shorts_first(child)

    # Again (a resume): no new Shorts; the cut is already there.
    again = session_split.split(Project.load(p.id), client)
    assert len(again["shorts"]) == 2 and len(client.cuts) == 1


def test_the_produce_pipeline_queues_the_sessions_shorts(projects, monkeypatch, tmp_path):
    from app.api import produce_api
    words, _, _ = _session_words()
    recording = tmp_path / "take.mp4"
    recording.write_bytes(b"video")
    monkeypatch.setattr(session_split, "extract_clip", lambda rec, a, b, out: open(out, "wb").close() or out)
    queued = []
    monkeypatch.setattr(produce_api.produce_queue, "add", lambda pid, **kw: queued.append((pid, kw)) or {"id": "q"})
    # A project set to Shorts first by hand, its Shorts not written by the Studio: cut at the silences.
    p = _project(buzzedit_project_id="be1", recording_path=str(recording), session_format="shorts_first",
                 session_shorts_count=2)
    produce_api._split_session(p.id, _Client(words))
    assert len(queued) == 2 and all(kw["mode"] == "record_first" for _, kw in queued)
    from core.models.project import Project
    assert all(s["queued"] for s in Project.load(p.id).metadata["session_split"]["shorts"])
    produce_api._split_session(p.id, _Client(words))
    assert len(queued) == 2


def test_a_session_without_the_greeting_stops_with_what_to_do(projects):
    words, _, long_at = _session_words()
    p = _project(buzzedit_project_id="be1", session_format="shorts_first")
    with pytest.raises(session_split.SessionSplitError, match="Long video starts at"):
        session_split.split(p, _Client(words[:long_at]))


def test_a_project_from_before_sessions_is_never_split(projects):
    """The channel default alone, no Shorts written: the whole recording is
    the long video, even when a cold open comes before the greeting."""
    words, _, _ = _session_words()
    client = _Client(words)
    assert session_split.split(_project(buzzedit_project_id="be1"), client) is None
    assert client.cuts == []


def test_a_misheard_greeting_falls_back_to_where_the_script_begins(projects):
    shorts, t = _words("Raat ke teen baje darwaza teen baar khatka aur phir koi andar aaya " * 3)
    garbled, t = _words("hilo dushton merena aham sudha aur aap dek rahe hain raath", t + 4.0)
    story, _ = _words("Uss raat Kishan ki duty kabristan ke gate par thi aur hawa bilkul band thi", t + 0.3)
    words = shorts + garbled + story
    for k, w in enumerate(words):
        w["tl_start"], w["tl_end"] = k * 0.4, k * 0.4 + 0.3
    p = _project(buzzedit_project_id="be1", session_format="shorts_first")
    with open(os.path.join(p.get_project_dir(), "script", "draft.md"), "w", encoding="utf-8") as f:
        f.write("Hello doston, mera naam hai Sudhansu aur aap dekh rahe hain Raat 3 Baje. "
                "Uss raat Kishan ki duty kabristan ke gate par thi aur hawa bilkul band thi.\n")
    p.assets["script"] = "script/draft.md"
    p.save()
    record = session_split.split(p, _Client(words))
    assert record["how"] == "script" and record["boundary_s"] == garbled[0]["start"]


# --- face first ------------------------------------------------------------------------------

def test_face_first_keeps_the_opening_on_the_face_then_covers_everything():
    word_starts = [k * 0.5 for k in range(1200)]           # ten minutes of speech
    anchors = list(range(0, 1200, 20))                      # a picture every 10 s
    shots, stats = story_visuals.plan_timed_shots(anchors, word_starts, 600.0, 0.3, 8.0, 0.55, face_intro_s=90.0)
    first = min(word_starts[s["word"]] for s in shots)
    assert 80.0 <= first <= 102.0 and stats["face_intro_s"] == pytest.approx(first, abs=0.1)
    pictured = stats["video_s"] + stats["image_s"]
    assert pictured >= 0.97 * (600.0 - first)
    # Clips and stills keep the sliders' proportion (30 : 55).
    assert stats["video_s"] / pictured == pytest.approx(0.3 / 0.85, abs=0.08)
    # Mixed (the old way) is untouched: pictures from the first word.
    shots, stats = story_visuals.plan_timed_shots(anchors, word_starts, 600.0, 0.3, 8.0, 0.55)
    assert min(word_starts[s["word"]] for s in shots) < 15.0 and "face_intro_s" not in stats


def test_a_full_style_face_first_script_keeps_its_cards_and_prompts():
    text = ("## Chapter one\n[card: 30 days | kind=stat] Aaj main aapko bataunga " + "word " * 60
            + "[broll: a laptop on a desk at night] " + "more " * 300 + "\n")
    times = [k * 0.45 for k in range(365)]
    out, stats = story_visuals.apply_to_script(text, 0.3, None, word_times=times, duration_s=170.0,
                                               image_share=0.55, face_intro_s=60.0, story=False)
    assert "## Chapter one" in out and "[card: 30 days | kind=stat]" in out
    assert "a laptop on a desk at night" in out and "calm and eerie" not in out
    assert stats["face_intro_s"] > 0 and stats["removed"] == 0


def test_the_face_layout_comes_from_the_channel_and_the_project(projects, _config):
    from integrations.buzzedit_settings import face_intro_seconds, resolve_settings
    p = _project()
    settings, sources = resolve_settings("Raat3Baje", None, p)
    # creator rule 2026-11-23: face-first for 45 s is every channel's default
    assert settings["face_layout"] == "face_intro" and face_intro_seconds(settings) == 45
    _config["channel_formats"] = {"Raat3Baje": {"face_layout": "face_intro", "face_intro_seconds": 120}}
    settings, sources = resolve_settings("Raat3Baje", None, p)
    assert face_intro_seconds(settings) == 120 and sources["face_layout"] == "channel_format"
    p.metadata["video_settings"] = {"face_layout": "mixed"}
    assert face_intro_seconds(resolve_settings("Raat3Baje", None, p)[0]) == 0


def test_a_face_first_render_sends_its_own_coverage_live(projects):
    from app.api import produce_api
    p = _project(buzzedit_project_id="be1",
                 face_intro_render={"buzzedit_project_id": "be1", "intro_s": 92.0, "coverage": 0.9})
    settings = {"face_layout": "face_intro", "face_intro_seconds": 90, "video_broll_share": 0.3,
                "image_broll_share": 0.55, "visual_style": "story"}
    mix = produce_api.face_intro_mix(p, settings)
    assert mix["video_broll_share"] + mix["image_broll_share"] == pytest.approx(0.9, abs=0.002)
    assert mix["face_intro_s"] == 92.0
    live = produce_api.live_settings_for({**settings, **mix})
    assert live["target_coverage"] == pytest.approx(0.9, abs=0.002)
    # Another BuzzEdit project (a new recording) is not face-first until timed again.
    p.metadata["buzzedit_project_id"] = "be2"
    assert produce_api.face_intro_mix(p, settings) is None


# --- research-first SEO -------------------------------------------------------------------------

class _ChatLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []
        self.last_response_simulated = False

    def generate_chat(self, system_prompt, messages, require_json=False, tier=None, temperature=None):
        self.seen.append([dict(m) for m in messages])
        return self.replies.pop(0)


class _SeoAgent:
    system_prompt = "seo"
    model_tier = "premium"
    temperature = 0.6

    def __init__(self, llm):
        self.llm_service = llm

    def refresh_prompt(self):
        pass


def test_the_seo_step_researches_demand_before_the_package(projects, monkeypatch):
    from runtime import research_loop, seo_research
    monkeypatch.setattr(seo_research, "suggest", lambda seed, limit=10: [f"{seed} hindi", f"{seed} real story"])
    monkeypatch.setattr(research_loop, "youtube_results", lambda q, limit=8: f"YouTube results for '{q}': 1.2M views")
    monkeypatch.setattr(seo_research, "own_channel_text", lambda brand, limit=15: "Raat3Baje's recent uploads: x")
    package = {"research": {"search_demand": [{"query": "masaan ki kahani", "evidence": "autocomplete"}],
                            "virality": {"score": 72, "why": "demand, weak competition"}},
               "titles": [{"title": "Masaan Ki Raat -- Rule No. 7", "why": "rules demand"}],
               "description": "Masaan ki raat...", "tags": ["masaan", "horror story"], "hashtags": ["#horror"]}
    llm = _ChatLLM([json.dumps(package),                                     # a guess: sent back
                    "[YT_SUGGEST: masaan]\n[YOUTUBE_SEARCH: masaan horror story]\n[OWN_CHANNEL]",
                    json.dumps(package)])
    logs = []
    out = seo_research.run(_SeoAgent(llm), _project(), "TASK", logs.append)
    assert out["turns"] == 3 and out["calls"] == ["autocomplete: masaan", "youtube search: masaan horror story",
                                                  "own channel"]
    assert "Demand snapshot" in llm.seen[0][0]["content"] and "masaan hindi" in llm.seen[2][-1]["content"]
    from integrations.youtube_publish import parse_seo_package
    assert parse_seo_package(out["raw"])["titles"] == ["Masaan Ki Raat -- Rule No. 7"]
    assert any("without a single lookup" in m for m in logs)


def test_the_session_api_sets_and_clears_a_projects_choices(projects, _config):
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    p = _project()
    url = f"/api/projects/{p.id}/session"
    body = client.put(url, json={"session_format": "long_only", "episode_format": "tantra", "split_at_s": 95.5}).json()
    assert body["session_format"] == "long_only" and body["episode_format"] == "tantra" and body["split_at_s"] == 95.5
    assert [f["key"] for f in body["episode_formats"]][:2] == ["rules", "real_encounter"]
    assert client.put(url, json={"episode_format": "nope"}).status_code == 400
    assert client.put(url, json={"shorts_count": 7}).status_code == 400
    body = client.put(url, json={"session_format": None}).json()
    assert body["session_format"] == "shorts_first" and body["session_format_source"] == "channel"
    state = client.put("/api/channel_formats/Raat3Baje", json={"face_layout": "face_intro", "next_format": "black_magic"}).json()
    assert state["channels"]["Raat3Baje"]["face_layout"] == "face_intro"
    assert state["pinned_format"]["Raat3Baje"] == state["next_format"]["Raat3Baje"] == "black_magic"
    assert client.put("/api/channel_formats/Khayal3Baje", json={"shorts_first": True}).status_code == 400
    assert client.put(f"/api/projects/{p.id}/video_settings", json={"face_layout": "sideways"}).status_code == 400
    eff = client.put(f"/api/projects/{p.id}/video_settings", json={"face_intro_seconds": 120}).json()["effective"]
    assert eff["face_layout"] == "face_intro" and eff["face_intro_seconds"] == 120


def test_raat3baje_has_five_story_formats_and_a_pinned_one_goes_first(monkeypatch, _config):
    from app.services import longform_nightly
    keys = [f["key"] for f in longform_nightly.formats_for("Raat3Baje")]
    assert keys == ["rules", "real_encounter", "story", "black_magic", "tantra"]
    assert "REAL HORROR ENCOUNTER" in longform_nightly.format_direction("Raat3Baje", "real_encounter")
    monkeypatch.setattr(longform_nightly, "_read_record", lambda: {})
    longform_nightly.set_pinned_format("Raat3Baje", "tantra")
    assert longform_nightly.next_format("Raat3Baje")[0] == "tantra"
    assert longform_nightly.next_format("Raat3Baje", 1)[0] == "rules"
    longform_nightly.set_pinned_format("Raat3Baje", None)
    assert longform_nightly.next_format("Raat3Baje")[0] == "rules"


def test_locked_format_is_returned_for_every_slot_and_invalid_is_ignored(monkeypatch, _config):
    from app.services import longform_nightly
    monkeypatch.setattr(longform_nightly, "_read_record", lambda: {})
    assert longform_nightly.formats_for("TheTallStoryteller")[0]["key"] == "detective"
    longform_nightly.set_locked_format("TheTallStoryteller", "detective")
    assert longform_nightly.next_format("TheTallStoryteller")[0] == "detective"
    assert longform_nightly.next_format("TheTallStoryteller", 1)[0] == "detective"
    longform_nightly.set_locked_format("TheTallStoryteller", "nonsense")
    assert longform_nightly._locked_format("TheTallStoryteller") is None
    assert longform_nightly.next_format("TheTallStoryteller", 1)[0] == "comedy"


def test_tall_storyteller_turns_are_mostly_detective_and_comedy_never_horror(monkeypatch, _config):
    from app.services import longform_nightly
    monkeypatch.setattr(longform_nightly, "_read_record", lambda: {})
    keys = [longform_nightly.next_format("TheTallStoryteller", i)[0] for i in range(5)]
    assert keys == ["detective", "comedy", "detective", "comedy", "crime"]
    assert "horror_tale" not in {f["key"] for f in longform_nightly.formats_for("TheTallStoryteller")}
    built = {"history": [{"built": [{"channel": "TheTallStoryteller", "format": "detective"},
                                    {"channel": "TheTallStoryteller", "format": "comedy"}]}]}
    monkeypatch.setattr(longform_nightly, "_read_record", lambda: built)
    assert longform_nightly.next_format("TheTallStoryteller")[0] == "detective"   # third in the turn
