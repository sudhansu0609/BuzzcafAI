"""Story adaptation (brief L2): a Story Library entry made into a Raat3Baje
script in the creator's voice, with the machine-writing detector."""
import json
import os
import sys
import time
import types
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.services import story_adapt
from app.services.writing_style import ai_tells

HUMAN = """Raat ke teen baje the. Main akela tha... bilkul akela. Phone ki battery do percent pe thi, aur bahar \
kuttey bhi chup ho gaye the. Ajeeb baat hai na? Kuttey kabhi chup nahi hote.

Phir awaaz aayi. Khat. Khat. Main uthkar khidki tak gaya aur parda hataya. Neeche gali mein ek aurat khadi \
thi, sar jhukaye, jaise kisi ka intezaar kar rahi ho. Maine socha koi padosan hogi. Lekin doston, us gali \
mein koi ghar hi nahi hai. Sach mein.

(pause)

Main peechhe hata. Dil zor zor se dhadak raha tha. Aur jab dobara jhaanka... woh wahan nahi thi. Woh meri \
khidki ke bilkul neeche thi. Upar dekh rahi thi. Seedha mujhe."""

MACHINE = """Raat ka andhera, sannata aur dar teeno gaon par chhaaye hue the. Yeh sirf ek purani haveli nahi \
thi, balki ek khaufnaak raaz ka ghar thi. Moreover, gaon ke log wahan jaane se hamesha darte the aur door \
rehte the. Haveli ki deewarein, khidkiyan aur darwaaze sab tooti hui haalat mein the. Ek taraf log use \
shaapit maante the, doosri taraf kuch log ise afwaah kehte the. It is important to note that har kahani ke \
peeche ek sach chhupa hota hai. Raat ko wahan se cheekhein aati thi, yani ki koi aatma wahan rehti thi. \
Furthermore, haveli ke maalik ka parivaar achanak gaayab ho gaya tha ek raat. Gaon ke bachche, budhe aur \
jawaan sab is baat ko jaante the — lekin koi kuch nahi kehta tha. Ultimately, sach kabhi samne nahi aaya \
aur raaz raaz hi reh gaya. Yeh kahani humein sikhati hai ki har purani cheez ke peeche ek itihaas hota hai."""


# --- ai_tells ------------------------------------------------------------------------

def test_a_human_hinglish_paragraph_reads_human():
    report = ai_tells(HUMAN)
    assert report["score"] < 30, report


def test_a_machine_paragraph_is_caught_with_its_tells():
    report = ai_tells(MACHINE)
    assert report["score"] > 60, report
    kinds = {t["kind"] for t in report["tells"]}
    assert {"triad", "contrast", "stock_transition", "hedge", "closing_moral", "uniform_length"} <= kinds
    for tell in report["tells"]:
        assert set(tell) == {"kind", "count", "examples"}


# --- the service ---------------------------------------------------------------------

ENTRIES = {
    "monkeys_paw": {"id": "monkeys_paw", "title": "The Monkey's Paw", "author": "W. W. Jacobs", "language": "en",
                    "source": "gutenberg", "source_url": "https://example.org/paw",
                    "rights": {"status": "public_domain", "death_year": 1943, "note": ""}, "words": 4000,
                    "first_lines": "Without, the night was cold and wet",
                    "text": "Without, the night was cold and wet. " * 40},
    "modern_one": {"id": "modern_one", "title": "A Modern Tale", "author": "Living Writer", "language": "hi",
                   "rights": {"status": "protected", "death_year": None, "note": "author alive"},
                   "text": "Ek aadmi ko raat mein ek awaaz sunai deti hai. " * 20},
}


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    from executive.project import project_manager
    import app.services as services_pkg
    monkeypatch.setattr(project_manager, "projects_dir", str(tmp_path / "projects"))
    monkeypatch.setattr("core.models.project._project_dir_for", lambda pid: str(tmp_path / "projects" / pid))
    monkeypatch.setattr("integrations.llm.load_config", lambda: {})
    fake = types.ModuleType("app.services.story_library")
    fake.entry = lambda entry_id: dict(ENTRIES[entry_id]) if entry_id in ENTRIES else None
    fake.entries = lambda: list(ENTRIES.values())
    monkeypatch.setitem(sys.modules, "app.services.story_library", fake)
    monkeypatch.setattr(services_pkg, "story_library", fake, raising=False)
    monkeypatch.setattr("integrations.idle_offload.offload_now", lambda reason="": False)
    return tmp_path


def _load(pid):
    from core.models.project import Project
    return Project.load(pid)


def test_adapt_writes_the_source_asset_and_the_metadata(sandbox):
    pid = story_adapt.adapt("monkeys_paw", parts=3, minutes_per_part=15, run=False)
    p = _load(pid)
    assert p.workflow_name == "raat3baje_adaptation" and p.brand == "Raat3Baje"
    assert p.current_step == "Adaptation"
    assert p.assets["source_story"] == "research/source_story.md"
    with open(os.path.join(p.get_project_dir(), "research", "source_story.md"), encoding="utf-8") as f:
        source = f.read()
    assert source.startswith("# The Monkey's Paw")
    assert "Author: W. W. Jacobs" in source and "Rights: public_domain (author died 1943)" in source
    assert "Without, the night was cold and wet." in source
    assert p.metadata["target_duration_minutes"] == 45
    a = p.metadata["adaptation"]
    assert (a["entry_id"], a["parts"], a["minutes_per_part"], a["rights"], a["mode"]) == \
        ("monkeys_paw", 3, 15, "public_domain", "adaptation")
    assert "Parts: 3, about 15 minutes each" in p.metadata["creator_instructions"]
    assert p.metadata["session_format"] == "shorts_first"       # Raat3Baje's default


def test_a_protected_story_is_refused_unless_inspired(sandbox):
    with pytest.raises(story_adapt.AdaptError):
        story_adapt.adapt("modern_one", run=False)
    pid = story_adapt.adapt("modern_one", inspired=True, run=False)
    p = _load(pid)
    assert p.metadata["adaptation"]["mode"] == "inspired"
    assert p.metadata["adaptation"]["rights"] == "protected"
    assert "[inspired-by: Living Writer, A Modern Tale; original story]" in p.metadata["creator_instructions"]
    assert "do not translate" in p.metadata["creator_instructions"]


def test_an_unknown_entry_is_refused(sandbox):
    with pytest.raises(story_adapt.AdaptError):
        story_adapt.adapt("nope", run=False)


def test_unknown_rights_count_as_protected(sandbox):
    ENTRIES["unsure"] = {**ENTRIES["monkeys_paw"], "id": "unsure", "rights": {"status": "unknown"}}
    try:
        with pytest.raises(story_adapt.AdaptError):
            story_adapt.adapt("unsure", run=False)
        pid = story_adapt.adapt("unsure", inspired=True, run=False)
        assert _load(pid).metadata["adaptation"]["mode"] == "inspired"
    finally:
        ENTRIES.pop("unsure")


# --- a collection, split into its stories ---------------------------------------------

def _para(word, n):
    return " ".join([word] * n) + "."


COLLECTION = "\n\n".join([
    "THE GHOST BOOK", "By Somebody", "CONTENTS", "The First Tale", "SECOND TALE", "A LONG ONE",
    "The First Tale", _para("pehla", 900),
    "SECOND TALE", _para("doosra", 2000), "II", _para("aage", 900),
    "Oh, Whistle, and I'll Come to You, My Lad", _para("seeti", 300),
    "A LONG ONE", _para("lamba", 13000),
])


def test_split_collection_finds_the_stories_and_skips_the_front():
    pieces = story_adapt.split_collection(COLLECTION)
    assert [p["title"] for p in pieces] == ["The First Tale", "SECOND TALE", "A LONG ONE"]
    assert pieces[0]["words"] == 900
    second = pieces[1]["text"]
    assert "aage" in second and "seeti" in second            # a numbered section and a short piece stay in it
    assert "pehla" not in second and "lamba" not in second
    assert story_adapt.default_piece(pieces) == 1               # the longest under 12,000 words
    assert story_adapt.split_collection("just one story.\n\nno headings.")[0]["title"] == ""


def test_a_contents_list_decides_the_headings():
    text = "\r\n".join([
        "Ghost Stories", "", "Contents", "", " Lost Hearts", " “Oh, Whistle, and I’ll Come to You, My Lad”", "",
        "LOST HEARTS", "", _para("dil", 900), "",
        "“OH, WHISTLE, AND I’LL COME TO YOU, MY LAD”", "", _para("seeti", 1000), "",
        "QUIS EST ISTE QUI VENIT", "", _para("seeti", 900),
    ])
    pieces = story_adapt.split_collection(text)
    assert [p["title"] for p in pieces] == ["LOST HEARTS", "OH, WHISTLE, AND I’LL COME TO YOU, MY LAD"]
    assert pieces[1]["words"] > 1900                            # the inscription stays inside the story


def test_adapt_writes_only_the_chosen_story_of_a_collection(sandbox):
    ENTRIES["book"] = {**ENTRIES["monkeys_paw"], "id": "book", "title": "The Ghost Book", "text": COLLECTION}
    try:
        pid = story_adapt.adapt("book", run=False)
        p = _load(pid)
        with open(os.path.join(p.get_project_dir(), "research", "source_story.md"), encoding="utf-8") as f:
            source = f.read()
        assert source.startswith("# SECOND TALE") and "doosra" in source and "pehla" not in source
        assert p.metadata["adaptation"]["story_title"] == "SECOND TALE"
        assert p.metadata["adaptation"]["story_index"] == 1
        pid = story_adapt.adapt("book", run=False, story_title="first tale")
        assert _load(pid).metadata["adaptation"]["story_title"] == "The First Tale"
        pid = story_adapt.adapt("book", run=False, story_index=2)
        assert _load(pid).metadata["adaptation"]["story_title"] == "A LONG ONE"
        with pytest.raises(story_adapt.AdaptError):
            story_adapt.adapt("book", run=False, story_index=7)
        listed = story_adapt.pieces("book")
        assert [(x["index"], x["title"]) for x in listed["pieces"]] == \
            [(0, "The First Tale"), (1, "SECOND TALE"), (2, "A LONG ONE")]
        assert listed["default"] == 1
    finally:
        ENTRIES.pop("book")


# --- a story, adapted part by part ----------------------------------------------------

def test_chunks_cut_between_paragraphs_with_even_words():
    text = "\n\n".join([_para("alpha", 100), _para("beta", 60), _para("gamma", 140)])
    chunks = story_adapt.chunk_paragraphs(text, 2)
    assert len(chunks) == 2
    assert "alpha" in chunks[0] and "beta" in chunks[0] and "gamma" not in chunks[0]
    assert chunks[1].startswith("gamma") and "beta" not in chunks[1]
    assert story_adapt.chunk_paragraphs(text, 5) == [_para("alpha", 100), _para("beta", 60), _para("gamma", 140)]


def test_the_adaptation_runs_once_per_part_and_joins_the_parts(sandbox, monkeypatch):
    from core.models.project import Project, StepExecution
    text = "\n\n".join([_para("alpha", 100), _para("beta", 60), _para("gamma", 140)])
    ENTRIES["three"] = {**ENTRIES["monkeys_paw"], "id": "three", "title": "Three Paragraphs", "text": text}
    runs, services = [], []

    class FakeEngine:
        def __init__(self, llm_service=None):
            services.append(llm_service)

        def execute_next(self, project_id, allow_all=None):
            p = Project.load(project_id)
            with open(os.path.join(p.get_project_dir(), p.assets["source_story"]), encoding="utf-8") as f:
                runs.append((p.current_step, f.read(), p.metadata["target_duration_minutes"]))
            k = len(runs)
            out = (f"# Part {k}\n\nHello doston, mera naam hai Sudhansu aur aap dekh rahe hain Raat 3 Baje.\n\n"
                   f"Kahani ka hissa {k} yahan chalta hai.\nPehli line.\nDoosri line.\nTeesri line {k}.")
            os.makedirs(os.path.join(p.get_project_dir(), "script"), exist_ok=True)
            with open(os.path.join(p.get_project_dir(), "script", "draft.md"), "w", encoding="utf-8") as f:
                f.write(out)
            p.assets["script"] = "script/draft.md"
            now = datetime.now().isoformat()
            p.steps_history.append(StepExecution(step_name=p.current_step, agent_name="StoryAdapter",
                                                 status="completed", started_at=now, completed_at=now))
            p.current_step = "Human Touch"
            p.save()
            return p

    monkeypatch.setattr("runtime.workflow.WorkflowEngine", FakeEngine)
    try:
        pid = story_adapt.adapt("three", parts=2, minutes_per_part=10, run=False)
        assert _load(pid).metadata["long_script_mode"] == "off"
        story_adapt.adapt_in_parts(pid)
    finally:
        ENTRIES.pop("three")

    assert services[0].config["long_script_mode"] == "off"
    assert [r[0] for r in runs] == ["Adaptation", "Adaptation"]
    first, second = runs[0][1], runs[1][1]
    assert "Part 1 of 2" in first and "alpha" in first and "beta" in first and "gamma" not in first
    assert "Part 2 of 2" in second and "gamma" in second and "alpha" not in second
    assert "The story so far" in second and "Teesri line 1." in second     # the previous part's last lines
    assert [r[2] for r in runs] == [10, 10]                      # each part's own target

    p = _load(pid)
    assert p.metadata["target_duration_minutes"] == 20             # restored
    assert p.assets["script"] == "script/script.md"
    d = p.get_project_dir()
    assert os.path.exists(os.path.join(d, "script", "part_1.md"))
    assert os.path.exists(os.path.join(d, "script", "part_2.md"))
    with open(os.path.join(d, "script", "script.md"), encoding="utf-8") as f:
        joined = f.read()
    assert [l for l in joined.splitlines() if l.startswith("# ")] == ["# Part 1", "# Part 2"]
    assert joined.count("Hello doston") == 1                       # the greeting once, in Part 1
    assert joined.index("Hello doston") < joined.index("# Part 2")
    with open(os.path.join(d, "research", "source_story.md"), encoding="utf-8") as f:
        assert "alpha" in f.read()                                 # the whole story is back after the run


def test_the_run_scores_human_touch_and_passes_it_a_second_time(sandbox, monkeypatch):
    from core.models.project import Project, StepExecution
    order = ["Adaptation", "Human Touch", "Shorts Scripts", "Visual Plan", "SEO & Thumbnail"]
    finals = [MACHINE, HUMAN]               # pass 1 still reads machine-made; pass 2 does not
    seen = []

    class FakeEngine:
        def __init__(self, llm_service=None):
            pass

        def execute_next(self, project_id, allow_all=None):
            p = Project.load(project_id)
            step = p.current_step
            seen.append((step, dict(p.assets)))
            os.makedirs(os.path.join(p.get_project_dir(), "script"), exist_ok=True)
            if step == "Adaptation":
                rel, text = "script/draft.md", MACHINE
                p.assets["script"] = rel
            elif step == "Human Touch":
                rel, text = "script/final.md", finals.pop(0)
                p.assets["script_final"] = rel
            else:
                rel, text = None, None
            if rel:
                with open(os.path.join(p.get_project_dir(), rel), "w", encoding="utf-8") as f:
                    f.write(text)
            now = datetime.now().isoformat()
            p.steps_history.append(StepExecution(step_name=step, agent_name="x", status="completed",
                                                 started_at=now, completed_at=now))
            p.current_step = order[order.index(step) + 1] if order.index(step) + 1 < len(order) else "Completed"
            p.save()
            return p

    monkeypatch.setattr("runtime.workflow.WorkflowEngine", FakeEngine)
    pid = story_adapt.adapt("monkeys_paw", run=False)
    out = story_adapt.run_steps(pid)

    p = _load(pid)
    # Through Visual Plan and SEO to the end since 2026-10-24 (no stop at Visual Plan).
    assert out["current_step"] == "Completed" == p.current_step
    steps = [s for s, _ in seen]
    assert steps == ["Adaptation", "Human Touch", "Human Touch", "Shorts Scripts", "Visual Plan", "SEO & Thumbnail"]
    assert seen[1][1]["ai_tells"] == "script/ai_tells.md"
    assert seen[1][1]["script"] == "script/script.md"          # the parts, joined
    assert seen[2][1]["script"] == "script/final.md"           # pass 2 rewrites pass 1's output
    assert p.assets["script"] == "script/script.md"             # and the adaptation is put back
    assert p.metadata["human_score"] < 30
    assert p.metadata["adaptation"]["human_passes"] == 2
    assert p.metadata["allow_all"] is False
    with open(os.path.join(p.get_project_dir(), "script", "ai_tells.md"), encoding="utf-8") as f:
        assert "Pass 2 of 2" in f.read()
    status = story_adapt.status(pid)
    assert status["state"] == "ready" and status["parts"] == 1 and status["rights"] == "public_domain"
    assert [s["name"] for s in status["steps"]][:2] == ["Adaptation", "Human Touch"]


# --- the workflow --------------------------------------------------------------------

def test_the_workflow_loads_with_its_steps_in_order():
    from core.workflow import workflow_registry
    workflow_registry.discover_workflows()
    wf = workflow_registry.get("raat3baje_adaptation")
    assert wf is not None
    assert [(s.name, s.agent_role, s.output_asset_type) for s in wf.steps] == [
        ("Adaptation", "StoryAdapter", "script"),
        ("Human Touch", "HumanTouch", "script_final"),
        ("Shorts Scripts", "ShortsWriter", "shorts_set"),
        ("Visual Plan", "PromptEngineer", "visual_plan"),
        ("SEO & Thumbnail", "SEOManagerAgent", "seo_package"),
    ]
    assert wf.steps[0].input_assets == ["source_story"]
    assert wf.steps[1].input_assets == ["script", "ai_tells"]
    assert wf.steps[2].when == "shorts_first"
    assert [s.requires_approval for s in wf.steps] == [False, False, True, False, True]


# --- the routes ----------------------------------------------------------------------

def test_routes(sandbox, monkeypatch):
    from app.main import app
    client = TestClient(app)

    created = client.post("/api/stories/adapt", json={"entry_id": "monkeys_paw", "parts": 2, "run": False}).json()
    pid = created["project_id"]
    assert created["state"] == "created"
    status = client.get(f"/api/stories/adapt/{pid}").json()
    assert (status["project_id"], status["state"], status["parts"], status["rights"]) == \
        (pid, "created", 2, "public_domain")
    assert status["human_score"] is None and status["steps"] == []

    assert client.post("/api/stories/adapt", json={"entry_id": "modern_one", "run": False}).status_code == 400
    assert client.get("/api/stories/adapt/jobs/none").status_code == 404
    assert client.get("/api/stories/adapt/no_such_project").status_code == 404
    listed = client.get("/api/stories/adapt/pieces/monkeys_paw").json()
    assert listed["pieces"] == [{"index": 0, "title": "The Monkey's Paw", "words": 280}]
    assert client.get("/api/stories/adapt/pieces/nope").status_code == 404
    bad = client.post("/api/stories/adapt", json={"entry_id": "monkeys_paw", "story_index": 3, "run": False})
    assert bad.status_code == 400

    monkeypatch.setattr(story_adapt, "run_steps", lambda project_id, progress: {"project_id": project_id})
    job = client.post("/api/stories/adapt", json={"entry_id": "modern_one", "inspired": True}).json()
    for _ in range(50):
        polled = client.get(f"/api/stories/adapt/jobs/{job['job_id']}").json()
        if polled["state"] != "running":
            break
        time.sleep(0.05)
    assert polled["state"] == "done" and polled["result"]["project_id"] == job["project_id"]
