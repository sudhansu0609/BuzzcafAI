"""Auto Story (AUTO_STORY_PLAN.md §3.3, §3.4, §3.7): narration, take, queue,
watcher, publishing, make(), settings and the routes. BuzzEdit, the synthetic
take, the production queue and YouTube are all faked. A reel format's run()
(REELS_DESK_PLAN.md VR5) takes a different, shorter path -- narration ->
`StoryReelPlanner` -> BuzzEdit's vibe-reel renderer -> Instagram package, no
take and no production queue -- with the planner and the renderer faked too;
the long-story path keeps the original pipeline, exercised with a landscape
project."""
import json
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services import auto_story, produce_queue, shorts_desk
from core.models import project as project_model
from core.models.project import Project
from integrations import youtube_publish
from integrations.buzzedit_client import BuzzEditClient

#: Captured before the autouse fixture below replaces `direct_narration` --
#: the real function, for the fidelity-gate tests that exercise it directly.
_REAL_DIRECT_NARRATION = auto_story.direct_narration


@pytest.fixture(autouse=True)
def _no_director(monkeypatch):
    """The NarrationDirector pass (Devanagari for the voice engine) is a model
    call; the tests narrate the text as written."""
    from app.services import auto_story
    monkeypatch.setattr(auto_story, "direct_narration", lambda text, channel, progress=None, **_: text)

@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(project_model, "PROJECTS_DIR", str(root), raising=False)
    monkeypatch.setattr(project_model, "_project_dir_for", lambda pid: str(root / pid), raising=False)
    import core.paths
    monkeypatch.setattr(core.paths, "PROJECTS_DIR", str(root))
    monkeypatch.setattr(auto_story, "STORE_DIR", str(tmp_path / "auto_story"))
    monkeypatch.setattr(auto_story, "_sleep", lambda s: None)
    monkeypatch.setattr(auto_story, "_live", {})
    monkeypatch.setattr(auto_story, "_watchers", {})
    from integrations import instagram_publish as instagram_publish_module
    monkeypatch.setattr(instagram_publish_module, "SETTINGS_FILE", tmp_path / "instagram_settings.json")
    # A plain channel-only route, same name as the channel, so the posting
    # tests below need not care about routing unless that is what they test.
    instagram_publish_module.set_routes({"Raat3Baje": "Raat3Baje"})

    # BuzzEdit narration (§3.1)
    wav = tmp_path / "engine_out.wav"
    wav.write_bytes(b"RIFF....WAVE")
    calls = {"post": [], "add": [], "upload": [], "take": [], "agent": [], "vibe_body": []}

    def post(body):
        calls["post"].append(body)
        return {"job_id": "n1", "state": "running", "message": "queued"}

    monkeypatch.setattr(auto_story, "_narration_post", post)
    monkeypatch.setattr(auto_story, "_narration_job", lambda jid: {
        "job_id": jid, "state": "done", "message": "done",
        "result": {"wav": str(wav), "seconds": 3.2, "duration_s": 61.0, "engine": "kokoro", "converted": True}})

    # The synthetic take (§3.2), not built yet by S1
    clip = tmp_path / "face.mp4"
    clip.write_bytes(b"clip")
    fake = types.ModuleType("integrations.synthetic_take")
    fake.face_intro_clip_for = lambda brand: str(clip)

    def build_take(project, narration_wav, *, orientation, face_intro_clip, still=None, out_dir=None):
        calls["take"].append({"wav": narration_wav, "orientation": orientation, "clip": face_intro_clip})
        out = root / project.id / "recording" / "take_1.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"take")
        return {"path": str(out), "duration_s": 73.5, "face_intro_s": 12.5, "orientation": orientation}

    fake.build_take = build_take
    import integrations
    monkeypatch.setitem(sys.modules, "integrations.synthetic_take", fake)
    monkeypatch.setattr(integrations, "synthetic_take", fake, raising=False)

    # The production queue
    final = tmp_path / "rec_final.mp4"
    final.write_bytes(b"final video")
    polls = {"n": 0}

    def add(project_id, **kw):
        calls["add"].append({"project_id": project_id, **kw})
        return {"id": "q1", "project_id": project_id, "status": "queued"}

    def snapshot():
        polls["n"] += 1
        pid = calls["add"][-1]["project_id"]
        if polls["n"] < 2:
            return {"items": [{"id": "q1", "project_id": pid, "status": "running"}]}
        p = Project.load(pid)
        p.metadata["final_output_path"] = str(final)
        p.save()
        return {"items": [{"id": "q1", "project_id": pid, "status": "done"}]}

    monkeypatch.setattr(produce_queue, "add", add)
    monkeypatch.setattr(produce_queue, "snapshot", snapshot)
    monkeypatch.setattr(produce_queue, "active_item_for", lambda pid: None)
    monkeypatch.setattr(produce_queue, "latest_item_for", lambda pid: None)

    # YouTube and the cover frame
    monkeypatch.setattr(youtube_publish, "channel_for_brand", lambda brand: "UC1")
    monkeypatch.setattr(youtube_publish, "status", lambda: {"channels": [{"id": "UC1", "signed_in": True}]})

    def upload(path, **kw):
        calls["upload"].append({"path": path, **kw})
        return {"video_id": "vid1", "url": "https://youtu.be/vid1", "privacy": "unlisted"}

    monkeypatch.setattr(youtube_publish, "upload", upload)
    monkeypatch.setattr(auto_story, "_cover_frame", lambda video, out: open(out, "wb").write(b"jpg"))

    # StoryReelPlanner and BuzzEdit's vibe-reel renderer (REELS_DESK_PLAN.md VR5): a
    # reel run never reaches the take or the production queue, so these are the only
    # mocks it needs past narration.
    def agent_json(agent, task):
        calls["agent"].append((agent, task))
        if agent != "StoryReelPlanner":
            return None
        n = max(3, round(task["seconds"] / 4.5))
        return {"world": "a dim Rajasthani haveli courtyard at night", "art_style": "real",
                "character": {"name": "Raj", "description": "a lean man in his 30s, a plain kurta", "gender": "male"},
                "shots": [{"prompt": f"corner {i} of the haveli courtyard, portrait, real",
                          "motion": "a flame swaying" if i % 3 == 0 else None,
                          "seconds": 5, "kind": "video" if i % 3 == 0 else "still",
                          "shows_character": i == 1} for i in range(n)]}

    monkeypatch.setattr(shorts_desk, "_agent_json", agent_json)

    vibe_out_dirs = {}

    def vibe_reel(self, body):
        calls["vibe_body"].append(body)
        job_id = f"vibe{len(calls['vibe_body'])}"
        vibe_out_dirs[job_id] = body["out_dir"]
        return {"job_id": job_id}

    def vibe_reel_job(self, job_id):
        stage_dir = Path(vibe_out_dirs[job_id])
        stage_dir.mkdir(parents=True, exist_ok=True)
        video = stage_dir / "reel.mp4"
        video.write_bytes(b"vibe video")
        nomusic = stage_dir / "reel_nomusic.mp4"
        nomusic.write_bytes(b"vibe video nomusic")
        cover = stage_dir / "cover.jpg"
        cover.write_bytes(b"vibe cover")
        return {"state": "done", "progress": 1.0, "message": "Done",
                "result": {"video": str(video), "video_nomusic": str(nomusic), "cover": str(cover),
                          "duration_s": 42.0, "failures": []}}

    monkeypatch.setattr(BuzzEditClient, "vibe_reel", vibe_reel)
    monkeypatch.setattr(BuzzEditClient, "vibe_reel_job", vibe_reel_job)

    def make_short(pid="reel_1", brand="Raat3Baje"):
        p = Project(id=pid, name="Raat ke niyam", brand=brand, workflow_name="shorts_ready",
                    metadata={"orientation": "vertical", "short_format": "rules_horror"})
        p.save()
        d = root / pid
        (d / "script").mkdir(parents=True, exist_ok=True)
        (d / "publish").mkdir(parents=True, exist_ok=True)
        (d / "script" / "short_script.md").write_text("# Raat ke niyam\n\nNiyam ek: darwaza mat kholna. (pause)\n",
                                                       encoding="utf-8")
        (d / "publish" / "short_package.json").write_text(json.dumps(
            {"title": "Raat ke niyam", "caption": "Teen baje ke niyam", "hashtags": ["#horror", "raat3baje"]}),
            encoding="utf-8")
        p.assets["script"] = "script/short_script.md"
        p.save()
        return p

    def make_long(pid="long_1", brand="Raat3Baje"):
        """A landscape, `long_story`-format project: the old take + production-queue
        path (VR5 leaves it unchanged)."""
        p = Project(id=pid, name="Raat ki lambi kahani", brand=brand, workflow_name="shorts_ready",
                    metadata={"orientation": "landscape", "auto_story": {"format": auto_story.LONG_STORY}})
        p.save()
        d = root / pid
        (d / "script").mkdir(parents=True, exist_ok=True)
        (d / "publish").mkdir(parents=True, exist_ok=True)
        (d / "script" / "script.md").write_text(
            "Ek purane haveli ki baat hai. Darwaza khud hi khulne laga tha. (pause)\n", encoding="utf-8")
        (d / "publish" / "short_package.json").write_text(json.dumps(
            {"title": "Raat ki lambi kahani", "caption": "Ek lambi kahani", "hashtags": ["#horror", "raat3baje"]}),
            encoding="utf-8")
        p.assets["script"] = "script/script.md"
        p.save()
        return p

    return types.SimpleNamespace(root=root, calls=calls, make_short=make_short, make_long=make_long,
                                 final=final, tmp=tmp_path)


def test_run_renders_a_story_reel_through_buzzedit_and_packages(env):
    """REELS_DESK_PLAN.md VR5: a reel format's run() narrates, plans the
    shots with StoryReelPlanner and renders through BuzzEdit's vibe-reel
    narration mode -- no take, no production queue, no watcher."""
    env.make_short()
    rec = auto_story.run("reel_1")
    assert rec["state"] == "packaged" and rec["orientation"] == "vertical" and rec["format"] == "rules_horror"

    body = env.calls["post"][0]
    assert "darwaza mat kholna" in body["text"] and "# Raat" not in body["text"]
    assert body["voice"] == "sudhansu_horror"  # Raat3Baje's own default (F8); run() gave none
    assert (env.root / "reel_1" / "audio" / "narration.wav").read_bytes() == b"RIFF....WAVE"
    assert env.calls["take"] == [] and env.calls["add"] == []

    agent, task = env.calls["agent"][0]
    assert agent == "StoryReelPlanner" and task["channel"] == "Raat3Baje" and task["format"] == "rules_horror"
    assert "darwaza mat kholna" in task["script"]

    reel_body = env.calls["vibe_body"][0]
    assert reel_body["out_dir"].replace("\\", "/").endswith("reel_1/production/vibe_reel")
    assert reel_body["name"] == "reel" and reel_body["art_style"] == "real"
    assert reel_body["world"] == "a dim Rajasthani haveli courtyard at night"
    assert reel_body["narration"]["path"].endswith("narration.wav") and reel_body["narration"]["language"] == "hi"
    assert reel_body["captions"] == {"style": "phrases"}
    assert "lines" not in reel_body and "cards" not in reel_body
    assert reel_body["character"]["name"] == "Raj"

    pkg = env.root / "reel_1" / "publish" / "instagram"
    assert (pkg / "reel.mp4").read_bytes() == b"vibe video"
    assert (pkg / "reel_nomusic.mp4").read_bytes() == b"vibe video nomusic"
    assert (pkg / "cover.jpg").read_bytes() == b"vibe cover"
    assert "#horror" in (pkg / "caption.txt").read_text(encoding="utf-8")

    assert rec["posted"] == {"instagram": "packaged", "package_dir": str(pkg)}
    assert rec["final"] == str(pkg / "reel.mp4")
    assert env.calls["upload"] == []  # a reel is Instagram-only, never YouTube

    p = Project.load("reel_1")
    assert p.metadata["auto_story"]["state"] == "packaged"
    assert p.assets["story_reel_plan"] == "production/story_reel_plan.json"
    assert [r["project_id"] for r in auto_story.list_records()] == ["reel_1"]


# --- word budget (REELS_DESK_PLAN.md VR9) ---------------------------------------------

def test_length_seconds_parses_every_shorts_desk_length_pick(env):
    assert auto_story.length_seconds("1 minute (60 seconds)") == 60.0
    assert auto_story.length_seconds("90 seconds") == 90.0
    assert auto_story.length_seconds("75 seconds (Short)") == 75.0
    assert auto_story.length_seconds("2 minutes") == 120.0
    assert auto_story.length_seconds("3 minutes") == 180.0
    assert auto_story.length_seconds("Short (4-8 lines)") is None
    assert auto_story.length_seconds(None) is None


def test_word_budget_uses_the_channels_resolved_mood(env):
    # Raat3Baje defaults to horror_narrator, measured 2026-10-24 at 2.06 words/s.
    assert auto_story.words_per_second("Raat3Baje") == auto_story.WORDS_PER_SECOND_BY_MOOD["horror_narrator"]
    assert auto_story.word_budget("Raat3Baje", "1 minute (60 seconds)") == round(60 * 2.25)   # tempo 0.90, 2026-10-24
    # Life3Baje has no saved/default mood: falls back to "steady" (2.5 words/s, estimated).
    assert auto_story.words_per_second("Life3Baje") == auto_story.WORDS_PER_SECOND_DEFAULT
    assert auto_story.word_budget("Life3Baje", "1 minute (60 seconds)") == 150
    # A length pick with no seconds in it (a poem) carries no budget.
    assert auto_story.word_budget("Raat3Baje", "Short (4-8 lines)") is None
    assert auto_story.word_budget("Raat3Baje", None) is None
    # A saved mood is picked up too.
    auto_story.set_settings({"voice_style": {"Raat3Baje": {"mood": "intense"}}})
    assert auto_story.word_budget("Raat3Baje", "1 minute (60 seconds)") == round(60 * 2.6)


def test_narration_overrun_only_warns_the_record_does_not_fail(env, monkeypatch):
    """REELS_DESK_PLAN.md VR9: a narration that runs well past the reel's own
    target length (189 s for a 60 s ask, the real 2026-10-24 failure) is
    recorded as a warning, not a failure -- the shot plan covers what was
    actually said."""
    env.make_short()
    project = Project.load("reel_1")
    project.metadata["auto_story"] = {"length": "1 minute (60 seconds)"}
    project.save()
    monkeypatch.setattr(auto_story, "_narration_job", lambda jid: {
        "job_id": jid, "state": "done", "message": "done",
        "result": {"wav": str(env.tmp / "engine_out.wav"), "seconds": 3.2, "duration_s": 189.0,
                  "engine": "kokoro", "converted": True}})
    rec = auto_story.run("reel_1")
    assert rec["state"] == "packaged"
    assert rec["warnings"] and "189" in rec["warnings"][0] and "60" in rec["warnings"][0]


def test_narration_within_target_carries_no_overrun_warning(env):
    env.make_short()
    project = Project.load("reel_1")
    project.metadata["auto_story"] = {"length": "1 minute (60 seconds)"}
    project.save()
    rec = auto_story.run("reel_1")   # env's default narration duration_s is 61.0
    assert rec["state"] == "packaged"
    assert not rec.get("warnings")


def test_overrun_threshold_is_1_5x_the_chosen_length(env, monkeypatch):
    """2026-10-24 creator follow-up: the length pick is a target, not a cap,
    and the overrun warning is relative to it -- only past 1.5x (90 s for a
    60 s ask); 85 s must not warn, 100 s must."""
    assert auto_story.NARRATION_OVERRUN_FACTOR == 1.5

    def with_duration(seconds):
        env.make_short()
        project = Project.load("reel_1")
        project.metadata["auto_story"] = {"length": "1 minute (60 seconds)"}
        project.save()
        monkeypatch.setattr(auto_story, "_narration_job", lambda jid: {
            "job_id": jid, "state": "done", "message": "done",
            "result": {"wav": str(env.tmp / "engine_out.wav"), "seconds": 3.2, "duration_s": seconds,
                      "engine": "kokoro", "converted": True}})
        return auto_story.run("reel_1")

    rec = with_duration(85.0)
    assert rec["state"] == "packaged" and not rec.get("warnings")
    rec2 = with_duration(100.0)
    assert rec2["state"] == "packaged" and rec2["warnings"] and "100" in rec2["warnings"][0]


def test_vibe_job_retries_once_on_a_transient_error(env, monkeypatch):
    attempts = {"n": 0}
    good_vibe_reel = BuzzEditClient.vibe_reel

    def flaky(self, body):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("BuzzEdit busy")
        return good_vibe_reel(self, body)

    monkeypatch.setattr(BuzzEditClient, "vibe_reel", flaky)
    env.make_short()
    rec = auto_story.run("reel_1")
    assert attempts["n"] == 2
    assert rec["state"] == "packaged"


def test_vibe_job_failure_after_one_retry_is_recorded_not_delivered(env, monkeypatch):
    def always_fails(self, body):
        raise RuntimeError("ComfyUI offline")

    monkeypatch.setattr(BuzzEditClient, "vibe_reel", always_fails)
    env.make_short()
    with pytest.raises(RuntimeError, match="ComfyUI offline"):
        auto_story.run("reel_1")
    rec = Project.load("reel_1").metadata["auto_story"]
    assert rec["state"] == "failed" and "ComfyUI offline" in rec["error"]
    assert not (env.root / "reel_1" / "publish" / "instagram" / "reel.mp4").exists()


def test_long_story_path_still_enqueues_as_before(env, monkeypatch):
    """VR5 leaves the landscape / long-story path on the original pipeline:
    take, production queue, watcher, YouTube when signed in and approved
    (STUDIO_DIRECTOR_PLAN.md: ask before publishing, Fable review #10)."""
    monkeypatch.setattr(youtube_publish, "channel_for_brand", lambda brand: None)
    env.make_long()
    auto_story.run("long_1", publish=True)
    final = auto_story.wait("long_1", 10)
    assert final["state"] == "packaged"
    assert final["review"]["state"] == "needs_review"
    assert "waiting for" in final["posted"]["youtube"]["skipped"]  # not "no signed-in" yet: unapproved waits
    assert env.calls["upload"] == []
    assert env.calls["take"] and env.calls["add"]  # the old take + queue path ran

    # Approving is what actually tries YouTube -- here there is still no
    # signed-in channel, so it is skipped for that reason instead.
    approved = auto_story.approve("long_1")
    assert approved["review"]["state"] == "approved"
    assert "no signed-in" in approved["posted"]["youtube"]["skipped"]
    assert env.calls["upload"] == []


def test_approving_a_finished_long_story_posts_to_youtube(env):
    """Once approved (and a channel is signed in), `approve()` performs the
    real YouTube upload that `_watch` deferred."""
    env.make_long()
    auto_story.run("long_1", publish=True)
    final = auto_story.wait("long_1", 10)
    assert final["state"] == "packaged" and env.calls["upload"] == []

    approved = auto_story.approve("long_1")
    assert approved["review"]["state"] == "approved"
    assert approved["posted"]["youtube"]["video_id"] == "vid1"
    assert approved["state"] == "published"
    assert len(env.calls["upload"]) == 1

    # Idempotent: approving again never re-uploads.
    auto_story.approve("long_1")
    assert len(env.calls["upload"]) == 1


def test_narration_retries_then_fails_with_a_record(env, monkeypatch):
    def refuse(body):
        env.calls["post"].append(body)
        raise RuntimeError("a render is running")

    monkeypatch.setattr(auto_story, "_narration_post", refuse)
    env.make_short()
    with pytest.raises(RuntimeError):
        auto_story.run("reel_1")
    assert len(env.calls["post"]) == auto_story.NARRATION_ATTEMPTS
    rec = Project.load("reel_1").metadata["auto_story"]
    assert rec["state"] == "failed" and "render is running" in rec["error"]
    assert env.calls["add"] == []


def test_make_a_shorts_format_calls_find_and_build(env, monkeypatch):
    seen = {}

    def find(channel, fmt, filters=None, count=6, progress=None):
        seen["find"] = (channel, fmt, filters)
        return {"candidates": [{"title": "Night shift rules", "score": 80}]}

    def build(channel, fmt, cand):
        seen["build"] = (channel, fmt, cand["title"])
        return env.make_short("built_1").to_dict()

    def fake_run(project_id, **kw):
        seen["run"] = (project_id, kw)
        return {"project_id": project_id, "state": "queued"}

    monkeypatch.setattr(shorts_desk, "find", find)
    monkeypatch.setattr(shorts_desk, "build", build)
    monkeypatch.setattr(auto_story, "run", fake_run)
    out = auto_story.make("Raat3Baje", "rules_horror", "75 seconds (Short)", voice="sudhansu", publish=False,
                          style="cartoon")
    assert out["project_id"] == "built_1"
    assert seen["find"] == ("Raat3Baje", "rules_horror", {"length": "75 seconds (Short)"})
    assert seen["build"] == ("Raat3Baje", "rules_horror", "Night shift rules")
    assert seen["run"][1]["orientation"] == "vertical"
    p = Project.load("built_1")
    assert p.metadata["auto_story"]["format"] == "rules_horror"
    assert p.metadata["video_settings"]["art_style"] == "cartoon"
    with pytest.raises(ValueError):
        auto_story.make("Raat3Baje", "poem")


def test_make_applies_the_formats_own_art_style_when_none_is_named(env, monkeypatch):
    """SW3 (STICK_WORLD_PLAN.md): Beyond3Baje's `what_if` defaults to
    `stick_world` when the caller names no style; naming one still wins."""
    monkeypatch.setattr(shorts_desk, "find", lambda *a, **k: {"candidates": [{"title": "T", "score": 80}]})
    monkeypatch.setattr(shorts_desk, "build", lambda channel, fmt, cand: env.make_short("built_2", "Beyond3Baje").to_dict())
    monkeypatch.setattr(auto_story, "run", lambda project_id, **kw: {"project_id": project_id, "state": "queued"})
    auto_story.make("Beyond3Baje", "what_if", "75 seconds (Short)", voice="sudhansu", publish=False)
    assert Project.load("built_2").metadata["video_settings"]["art_style"] == "stick_world"
    monkeypatch.setattr(shorts_desk, "build", lambda channel, fmt, cand: env.make_short("built_3", "Beyond3Baje").to_dict())
    auto_story.make("Beyond3Baje", "what_if", "75 seconds (Short)", voice="sudhansu", publish=False, style="real")
    assert Project.load("built_3").metadata["video_settings"]["art_style"] == "real"


def test_settings_round_trip(env):
    s = auto_story.settings()
    assert s["per_channel"] == {"Raat3Baje": 1, "Life3Baje": 1, "Beyond3Baje": 0, "TheTallStoryteller": 0} \
        and s["publish"] is False
    out = auto_story.set_settings({"enabled": True, "per_channel": {"Beyond3Baje": 2, "Nope": 3},
                                   "formats": {"Beyond3Baje": ["what_if", "long_story", "poem"]},
                                   "face_intro_clips": {"Raat3Baje": "C:/clips/intro.mp4"}})
    again = auto_story.settings()
    assert again == out
    assert again["enabled"] is True and again["per_channel"]["Beyond3Baje"] == 2 and "Nope" not in again["per_channel"]
    assert again["formats"]["Beyond3Baje"] == ["what_if", "long_story"]
    assert again["face_intro_clips"] == {"Raat3Baje": "C:/clips/intro.mp4"}


def test_voice_style_settings_are_sanitised(env):
    # Raat3Baje has no saved voice_style: it defaults to horror_narrator (F8), not VOICE_STYLE_DEFAULT.
    assert auto_story.voice_style_for("Raat3Baje") == {"mood": "horror_narrator"}
    assert auto_story.voice_style_for("Life3Baje") == {"mood": "steady", "dramatic": "subtle"}
    out = auto_story.set_settings({"voice_style": {
        "Raat3Baje": {"mood": "eerie", "pace": 5, "word_gap_ms": 90, "dramatic": "strong", "nonsense": "x"},
        "Nope": {"mood": "warm"},
    }})
    assert out["voice_style"] == {"Raat3Baje": {"mood": "eerie", "dramatic": "strong", "pace": 1.3, "word_gap_ms": 90}}
    assert auto_story.voice_style_for("Raat3Baje") == out["voice_style"]["Raat3Baje"]
    # Invalid dramatic is dropped rather than saved.
    out2 = auto_story.set_settings({"voice_style": {"Raat3Baje": {"mood": "calm", "dramatic": "loud"}}})
    assert out2["voice_style"]["Raat3Baje"] == {"mood": "calm"}


def test_narration_uses_the_channels_voice_style(env, monkeypatch):
    auto_story.set_settings({"voice_style": {"Raat3Baje": {"mood": "eerie", "pace": 0.8, "dramatic": "strong"}}})
    seen = {}
    monkeypatch.setattr(auto_story, "direct_narration", lambda text, channel, progress=None, **_: (
        seen.update(dramatic_lookup=auto_story.voice_style_for(channel).get("dramatic")) or text))
    env.make_short()
    auto_story.run("reel_1")
    body = env.calls["post"][0]
    assert body["style"] == {"mood": "eerie", "pace": 0.8}
    assert "dramatic" not in body["style"]
    assert seen["dramatic_lookup"] == "strong"


def test_moods_route_falls_back_when_buzzedit_is_down(env, monkeypatch):
    from integrations.buzzedit_client import BuzzEditClient

    def down(self, path, timeout=None):
        raise RuntimeError("BuzzEdit down")

    monkeypatch.setattr(BuzzEditClient, "_get", down)
    rows = auto_story.moods()
    assert any(r["id"] == "steady" for r in rows) and rows == auto_story.FALLBACK_MOODS


def test_voice_preview_starts_a_job_and_reads_back_the_audio(env):
    started = auto_story.voice_preview_start("Raat3Baje")
    assert started["job_id"] == "n1"
    body = env.calls["post"][0]
    assert "(dramatic)" in body["text"] and "(normal)" in body["text"]
    assert body["style"] == {"mood": "horror_narrator"}      # Raat3Baje's own default (F8)
    assert body["voice"] == "sudhansu_horror"
    status = auto_story.voice_preview_status(started["job_id"])
    assert status["state"] == "done"
    path = auto_story.voice_preview_audio_path(started["job_id"])
    assert path.endswith("engine_out.wav")

    # A plain channel still previews his ordinary voice and the steady mood.
    env.calls["post"].clear()
    auto_story.voice_preview_start("Life3Baje")
    body = env.calls["post"][0]
    assert body["style"] == {"mood": "steady"} and body["voice"] == "sudhansu"


def test_default_voice_for_the_horror_channels_only(env):
    assert auto_story.default_voice_for("Raat3Baje") == "sudhansu_horror"
    assert auto_story.default_voice_for("Beyond3Baje") == "sudhansu_horror"
    assert auto_story.default_voice_for("Life3Baje") == "sudhansu"


def test_run_all_defaults_raat3baje_to_the_horror_voice(env, monkeypatch):
    auto_story.set_settings({"enabled": True, "per_channel": {"Raat3Baje": 1, "Life3Baje": 0},
                             "formats": {"Raat3Baje": ["rules_horror"]}})
    monkeypatch.setattr(shorts_desk, "_agent_json", lambda agent, task: None)
    seen = {}

    def fake_make(channel, fmt, length=None, **kw):
        seen[channel] = kw.get("voice")
        return {"project_id": "p1", "state": "packaged"}

    monkeypatch.setattr(auto_story, "make", fake_make)
    monkeypatch.setattr(auto_story, "wait", lambda pid, timeout=None: {"project_id": pid, "state": "packaged"})
    auto_story.run_all()
    assert seen["Raat3Baje"] == "sudhansu_horror"


def test_run_all_rotates_and_records(env, monkeypatch):
    auto_story.set_settings({"enabled": True, "per_channel": {"Raat3Baje": 2, "Life3Baje": 0},
                             "formats": {"Raat3Baje": ["rules_horror", "ghost_story"]}})
    monkeypatch.setattr(shorts_desk, "_agent_json", lambda agent, task: None)
    made = []

    def fake_make(channel, fmt, length=None, **kw):
        made.append((channel, fmt))
        return {"project_id": f"p{len(made)}", "state": "packaged"}

    monkeypatch.setattr(auto_story, "make", fake_make)
    monkeypatch.setattr(auto_story, "wait", lambda pid, timeout=None: {"project_id": pid, "state": "packaged",
                                                                       "name": pid, "posted": {"instagram": "packaged"}})
    out = auto_story.run_all()
    assert made == [("Raat3Baje", "rules_horror"), ("Raat3Baje", "ghost_story")]
    assert out["task"] == "auto_story" and len(out["made"]) == 2 and out["failed"] == []
    assert auto_story.settings()["last"]["made"][0]["project_id"] == "p1"


def test_the_report_has_a_made_by_itself_section(tmp_path, monkeypatch):
    from app.services import nightly_report
    nightly = tmp_path / "nightly"
    nightly.mkdir()
    monkeypatch.setattr(nightly_report, "NIGHTLY_DIR", nightly)
    monkeypatch.setattr(nightly_report, "REPORTS_DIR", nightly / "reports")
    (nightly / "last_run.json").write_text(json.dumps({
        "started_at": "2026-10-23T03:00:00", "finished_at": "2026-10-23T05:00:00", "scope": "all",
        "tasks": [{"task": "auto_story", "seconds": 3600,
                   "made": [{"channel": "Raat3Baje", "format": "rules_horror", "project_id": "p1", "name": "Niyam",
                             "state": "packaged", "posted": {"instagram": "packaged"}}],
                   "failed": [{"channel": "Life3Baje", "format": "poem", "error": "narration refused"}]}]}),
        encoding="utf-8")
    text = json.dumps(nightly_report.build(), ensure_ascii=False)
    assert "Made by itself" in text and "Niyam" in text and "narration refused" in text


def test_routes_answer(env, monkeypatch):
    from app.main import app
    from integrations.buzzedit_client import BuzzEditClient

    def down(self, path, timeout=None):
        raise RuntimeError("BuzzEdit down")

    monkeypatch.setattr(BuzzEditClient, "_get", down)
    client = TestClient(app)
    assert client.get("/api/auto_story/settings").json()["per_channel"]["Raat3Baje"] == 1
    assert client.post("/api/auto_story/settings", json={"publish": True}).json()["publish"] is True
    fmts = client.get("/api/auto_story/formats").json()
    assert {"key": "long_story", "label": "Long story (his face intro, then narration)"} in fmts["Raat3Baje"]
    assert any(f["key"] == "rules_horror" for f in fmts["Raat3Baje"])
    assert client.get("/api/auto_story/voices").json() == {"voices": ["sudhansu"]}
    moods_resp = client.get("/api/auto_story/moods").json()  # BuzzEdit down (above): the fallback table
    assert any(m["id"] == "steady" for m in moods_resp["moods"])
    assert client.post("/api/auto_story/voice_preview", json={"channel": "Nope"}).status_code == 400
    pv = client.post("/api/auto_story/voice_preview", json={"channel": "Raat3Baje"})
    assert pv.status_code == 200 and pv.json()["job_id"] == "n1"
    job_id = pv.json()["job_id"]
    assert client.get(f"/api/auto_story/voice_preview/{job_id}").json()["state"] == "done"
    audio = client.get(f"/api/auto_story/voice_preview/{job_id}/audio")
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/wav"
    assert client.get("/api/auto_story/records").json() == {"records": []}
    assert client.get("/api/auto_story/jobs/nope").status_code == 404
    assert client.get("/api/auto_story/missing_project").status_code == 404
    assert client.post("/api/auto_story/make", json={"channel": "Raat3Baje", "format": "poem"}).status_code == 400
    assert client.post("/api/auto_story/make", json={"channel": "Raat3Baje", "format": "long_story",
                                                    "length": "lots"}).status_code == 400
    env.make_short()
    assert client.get("/api/auto_story/reel_1").status_code == 404  # no record yet
    assert client.post("/api/auto_story/reel_1/open_package").status_code == 404

    started = {}
    monkeypatch.setattr(auto_story, "start_job", lambda kind, fn, *a, **kw: started.update(kind=kind, args=a, kw=kw)
                        or {"job_id": "j1", "state": "running"})
    r = client.post("/api/auto_story/reel_1/run", json={"publish": True})
    assert r.json()["job_id"] == "j1" and started["kind"] == "run" and started["kw"]["publish"] is True
    r = client.post("/api/auto_story/make", json={"channel": "Raat3Baje", "format": "long_story", "length": 25})
    assert r.status_code == 200 and started["args"] == ("Raat3Baje", "long_story", 25.0)


# --- posting to Instagram (REELS_DESK_PLAN.md R7) --------------------------------------------

def test_post_instagram_is_idempotent_and_can_be_forced(env, monkeypatch):
    from integrations import instagram_publish as ig

    env.make_short()
    auto_story.run("reel_1")
    auto_story.approve("reel_1")  # ask before publishing (Fable review #10): force=False needs this
    calls = []

    def fake_publish(channel, video, caption, thumb_offset_ms=None):
        calls.append({"channel": channel, "video": video, "caption": caption, "thumb_offset_ms": thumb_offset_ms})
        return {"media_id": "m1", "permalink": "https://instagram.com/reel/abc"}

    monkeypatch.setattr(ig, "publish_reel", fake_publish)
    posted = auto_story.post_instagram("reel_1")
    assert posted == {"permalink": "https://instagram.com/reel/abc", "media_id": "m1", "at": posted["at"]}
    assert len(calls) == 1 and calls[0]["channel"] == "Raat3Baje" and calls[0]["thumb_offset_ms"] == 1000
    assert "Teen baje" in calls[0]["caption"]

    # idempotent: a second call never posts again
    posted2 = auto_story.post_instagram("reel_1")
    assert posted2 == posted and len(calls) == 1

    # force re-posts
    auto_story.post_instagram("reel_1", force=True)
    assert len(calls) == 2


def test_post_instagram_records_the_api_error_without_raising(env, monkeypatch):
    from integrations import instagram_publish as ig

    env.make_short()
    auto_story.run("reel_1")
    auto_story.approve("reel_1")

    def fake_publish(channel, video, caption, thumb_offset_ms=None):
        raise ig.InstagramError("Instagram API error (190): token expired")

    monkeypatch.setattr(ig, "publish_reel", fake_publish)
    posted = auto_story.post_instagram("reel_1")
    assert "token expired" in posted["error"] and posted["at"]
    # not idempotent-blocked: an error is not a permalink, so a plain retry still posts
    assert auto_story.post_instagram("reel_1")["error"]


def test_post_instagram_without_a_package_raises(env):
    from core.models.project import Project

    p = Project(id="no_pkg", name="No package yet", brand="Raat3Baje", workflow_name="shorts_ready")
    p.save()
    with pytest.raises(ValueError):
        auto_story.post_instagram("no_pkg")


def test_post_instagram_without_approval_raises_unless_forced(env, monkeypatch):
    """STUDIO_DIRECTOR_PLAN.md: ask before publishing (Fable review #10) --
    `post_instagram(force=False)` posts approved items only."""
    from integrations import instagram_publish as ig

    env.make_short()
    auto_story.run("reel_1")
    with pytest.raises(ValueError, match="not approved"):
        auto_story.post_instagram("reel_1")

    def fake_publish(channel, video, caption, thumb_offset_ms=None):
        return {"media_id": "m1", "permalink": "https://instagram.com/reel/forced"}

    monkeypatch.setattr(ig, "publish_reel", fake_publish)
    # force=True bypasses the review gate (an explicit creator override).
    posted = auto_story.post_instagram("reel_1", force=True)
    assert posted["permalink"] == "https://instagram.com/reel/forced"


def test_post_instagram_route(env, monkeypatch):
    from app.main import app
    from integrations import instagram_publish as ig

    env.make_short()
    auto_story.run("reel_1")
    auto_story.approve("reel_1")
    monkeypatch.setattr(ig, "publish_reel", lambda channel, video, caption, thumb_offset_ms=None: (
        {"media_id": "m9", "permalink": "https://instagram.com/reel/m9"}))
    client = TestClient(app)
    r = client.post("/api/auto_story/reel_1/post_instagram")
    assert r.status_code == 200 and r.json()["permalink"] == "https://instagram.com/reel/m9"
    assert client.post("/api/auto_story/no_such_project/post_instagram").status_code == 404


def test_instagram_scheduler_posts_the_oldest_unposted_reel_only_when_enabled(env, monkeypatch):
    from datetime import datetime
    from core.models.project import Project
    from integrations import instagram_publish as ig

    def set_started(pid, when):
        p = Project.load(pid)
        rec = dict(p.metadata.get("auto_story") or {})
        rec["started_at"] = when
        p.metadata["auto_story"] = rec
        p.save()

    env.make_short(pid="reel_old")
    auto_story.run("reel_old")
    auto_story.approve("reel_old")  # ask before publishing: the scheduler posts approved items only
    set_started("reel_old", "2026-10-20T10:00:00")
    env.make_short(pid="reel_new")
    auto_story.run("reel_new")
    auto_story.approve("reel_new")
    set_started("reel_new", "2026-10-21T10:00:00")

    posted_calls = []

    def fake_publish(channel, video, caption, thumb_offset_ms=None):
        posted_calls.append((channel, video))
        return {"media_id": "m1", "permalink": "https://instagram.com/p/x"}

    monkeypatch.setattr(ig, "publish_reel", fake_publish)

    class FixedDateTime(datetime):
        _now_value = datetime(2026, 10, 24, 9, 0)

        @classmethod
        def now(cls, tz=None):
            return cls._now_value

    monkeypatch.setattr(auto_story, "datetime", FixedDateTime)

    # Disabled (the default): the tick posts nothing.
    auto_story._instagram_tick()
    assert posted_calls == []

    ig.set_account_settings("Raat3Baje", {"enabled": True, "post_times": ["09:00"]})
    auto_story._instagram_tick()
    assert len(posted_calls) == 1 and "reel_old" in posted_calls[0][1]

    # The same slot never fires twice in a day, even unposted work remains.
    auto_story._instagram_tick()
    assert len(posted_calls) == 1

    # The next day's slot posts the next-oldest unposted reel.
    FixedDateTime._now_value = datetime(2026, 10, 25, 9, 0)
    auto_story._instagram_tick()
    assert len(posted_calls) == 2 and "reel_new" in posted_calls[1][1]


def test_oldest_unposted_packaged_for_account_only_returns_approved_reels(env):
    """Ask before publishing (STUDIO_DIRECTOR_PLAN.md, Fable review #10): the
    scheduler's own candidate lookup skips a packaged reel until it is
    approved."""
    from integrations import instagram_publish as ig

    env.make_short()
    auto_story.run("reel_1")
    assert ig.account_for("Raat3Baje") == "Raat3Baje"
    assert auto_story._oldest_unposted_packaged_for_account("Raat3Baje") is None

    auto_story.approve("reel_1")
    candidate = auto_story._oldest_unposted_packaged_for_account("Raat3Baje")
    assert candidate is not None and candidate["project_id"] == "reel_1"


def test_instagram_due_fires_for_any_passed_time_not_just_an_exact_match(env):
    """2026-10-24, Fable review #11: `post_time <= now`, not an exact HH:MM
    match, so a tick that runs late never skips an overdue slot."""
    from datetime import datetime

    conf = {"enabled": True, "post_times": ["09:00", "09:05"], "last_fired": {}}
    assert auto_story._instagram_due(conf, datetime(2026, 10, 24, 9, 7)) == "09:00"
    conf["last_fired"] = {"09:00": "2026-10-24"}
    assert auto_story._instagram_due(conf, datetime(2026, 10, 24, 9, 7)) == "09:05"
    conf["last_fired"] = {"09:00": "2026-10-24", "09:05": "2026-10-24"}
    assert auto_story._instagram_due(conf, datetime(2026, 10, 24, 9, 7)) is None
    # Before the first slot, nothing is due yet.
    assert auto_story._instagram_due({"enabled": True, "post_times": ["09:00"], "last_fired": {}},
                                     datetime(2026, 10, 24, 8, 59)) is None


def test_life3baje_mood_reel_routes_to_a_different_account_by_default(env):
    """The creator's requirement: Life3Baje's mood reels post to a separate,
    calmer account (@khayal3bajefeels) from its ordinary reels."""
    from integrations import instagram_publish as ig

    assert ig.account_for("Life3Baje", "mood_reel") == "khayal3bajefeels"
    assert ig.account_for("Life3Baje") is None             # no plain Life3Baje route by default
    assert ig.account_for("Life3Baje", "rules_horror") is None   # only mood_reel is routed


def test_a_format_specific_route_wins_over_the_channel_route(env):
    from integrations import instagram_publish as ig

    ig.set_routes({"Life3Baje": "life3baje_main"})
    assert ig.account_for("Life3Baje", "mood_reel") == "khayal3bajefeels"   # still the more specific route
    assert ig.account_for("Life3Baje", "rules_horror") == "life3baje_main"
    assert ig.account_for("Life3Baje") == "life3baje_main"


def test_post_instagram_uses_the_account_routed_for_the_format(env, monkeypatch):
    """A Life3Baje mood reel posts through khayal3bajefeels, not Life3Baje's own account."""
    from core.models.project import Project
    from integrations import instagram_publish as ig

    ig.set_routes({"Life3Baje": "life3baje_main"})
    p = Project(id="mood_proj", name="Mood reel", brand="Life3Baje", workflow_name="shorts_ready",
                metadata={"auto_story": {"format": "mood_reel", "posted": {},
                                         "review": {"state": "approved", "at": "", "reason": None}}})
    p.save()
    d = env.root / "mood_proj" / "publish" / "instagram"
    d.mkdir(parents=True)
    (d / "reel.mp4").write_bytes(b"vid")
    (d / "caption.txt").write_text("a mood reel caption", encoding="utf-8")

    seen = {}

    def fake_publish(account, video, caption, thumb_offset_ms=None):
        seen["account"] = account
        return {"media_id": "m1", "permalink": "https://instagram.com/p/mood"}

    monkeypatch.setattr(ig, "publish_reel", fake_publish)
    posted = auto_story.post_instagram("mood_proj")
    assert posted["permalink"] == "https://instagram.com/p/mood"
    assert seen["account"] == "khayal3bajefeels"


def test_post_instagram_without_a_route_records_an_error_not_a_raise(env):
    from core.models.project import Project

    p = Project(id="unrouted", name="Unrouted", brand="Beyond3Baje", workflow_name="shorts_ready",
                metadata={"auto_story": {"review": {"state": "approved", "at": "", "reason": None}}})
    p.save()
    d = env.root / "unrouted" / "publish" / "instagram"
    d.mkdir(parents=True)
    (d / "reel.mp4").write_bytes(b"vid")
    posted = auto_story.post_instagram("unrouted")
    assert "No Instagram account is routed" in posted["error"]


# --- the approval gate (STUDIO_DIRECTOR_PLAN.md: ask before publishing; Fable review #10) ---

def test_approve_marks_the_record_without_touching_the_instagram_package(env):
    env.make_short()
    rec = auto_story.run("reel_1")
    assert rec["review"]["state"] == "needs_review"

    approved = auto_story.approve("reel_1")
    assert approved["review"]["state"] == "approved" and approved["review"]["reason"] is None
    assert approved["posted"]["instagram"] == "packaged"  # unchanged: posting is still its own step

    record = Project.load("reel_1").metadata["auto_story"]
    assert record["review"]["state"] == "approved"


def test_reject_records_the_reason_and_the_decision_log(env):
    env.make_short()
    auto_story.run("reel_1")
    rejected = auto_story.reject("reel_1", reason="Too generic; make the hook stronger.")
    assert rejected["review"]["state"] == "rejected"
    assert rejected["review"]["reason"] == "Too generic; make the hook stronger."

    log_path = Path(auto_story.STORE_DIR).parent / "decisions" / "log.jsonl"
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    entry = json.loads(lines[-1])
    assert entry["project_id"] == "reel_1" and entry["action"] == "reject"
    assert entry["reason"] == "Too generic; make the hook stronger."
    assert entry["channel"] == "Raat3Baje" and entry["format"] == "rules_horror"


def test_approve_and_reject_raise_for_a_project_with_no_record(env):
    p = Project(id="blank", name="Blank", brand="Raat3Baje", workflow_name="shorts_ready")
    p.save()
    with pytest.raises(ValueError):
        auto_story.approve("blank")
    with pytest.raises(ValueError):
        auto_story.reject("blank", reason="no record anyway")


def test_regenerate_reruns_make_with_the_same_channel_format_length_theme(env, monkeypatch):
    env.make_short()
    auto_story.run("reel_1")
    seen = {}

    def fake_make(channel, fmt, length=None, *, voice=auto_story.VOICE_DEFAULT, publish=False,
                 style=None, theme=None, progress=None):
        seen.update(channel=channel, fmt=fmt, length=length, publish=publish, theme=theme)
        return {"project_id": "reel_2", "state": "queued"}

    monkeypatch.setattr(auto_story, "make", fake_make)
    out = auto_story.regenerate("reel_1")
    assert out["project_id"] == "reel_2"
    assert seen["channel"] == "Raat3Baje" and seen["fmt"] == "rules_horror"


def test_regenerate_without_a_record_raises(env):
    p = Project(id="blank2", name="Blank", brand="Raat3Baje", workflow_name="shorts_ready")
    p.save()
    with pytest.raises(ValueError):
        auto_story.regenerate("blank2")


def test_approve_reject_regenerate_and_preview_routes(env, monkeypatch):
    from app.main import app

    env.make_short()
    auto_story.run("reel_1")
    client = TestClient(app)

    r = client.post("/api/auto_story/reel_1/approve")
    assert r.status_code == 200 and r.json()["review"]["state"] == "approved"
    assert client.post("/api/auto_story/no_such_project/approve").status_code == 404

    r2 = client.post("/api/auto_story/reel_1/reject", json={"reason": "redo the hook"})
    assert r2.status_code == 200
    assert r2.json()["review"] == {"state": "rejected", "at": r2.json()["review"]["at"], "reason": "redo the hook"}

    monkeypatch.setattr(auto_story, "start_job",
                        lambda kind, fn, *a, **k: {"job_id": "j1", "kind": kind, "state": "running"})
    r3 = client.post("/api/auto_story/reel_1/regenerate")
    assert r3.status_code == 200 and r3.json()["job_id"] == "j1"

    cover_path = Path(auto_story.record("reel_1")["cover"])
    video_r = client.get("/api/auto_story/reel_1/preview/video")
    assert video_r.status_code == 200
    cover_r = client.get("/api/auto_story/reel_1/preview/cover")
    assert cover_r.status_code == 200 and cover_path.is_file()
    assert client.get("/api/auto_story/reel_1/preview/nonsense").status_code == 404


# --- narration fidelity (2026-10-24, Fable review #12) ---------------------------------

def test_in_order_overlap_scores_the_fraction_of_words_found_in_order():
    original = auto_story._content_words("ek raat ghar laut raha tha jab usne ek awaaz suni")
    exact = auto_story._content_words("(pause) ek raat ghar laut raha tha jab usne ek awaaz suni")
    assert auto_story._in_order_overlap(original, exact) == 1.0

    reordered = auto_story._content_words("usne ek awaaz suni jab ghar laut raha tha ek raat")
    assert auto_story._in_order_overlap(original, reordered) < 1.0

    unrelated = auto_story._content_words("ek bilkul alag kahani jiska koi lena dena nahi")
    assert auto_story._in_order_overlap(original, unrelated) < auto_story.NARRATION_FIDELITY_MIN


def test_direct_narration_keeps_a_faithful_directed_text(monkeypatch, env):
    from app.services import shorts_desk

    script = ("Ek raat Delhi mein Sudhansu ghar laut raha tha jab usne peeche se ek awaaz suni jo "
              "use bula rahi thi bar bar uske naam se.")
    directed = "(pause) " + script.replace(".", "... (pause)")
    monkeypatch.setattr(shorts_desk, "_agent_json", lambda *a, **k: {"text": directed})
    project = env.make_short()
    out = _REAL_DIRECT_NARRATION(script, "Raat3Baje", project=project)
    # Kept, with its pause cues capped to one for a one-sentence text (the latest stays).
    assert out == auto_story.cap_pause_cues(directed)
    assert out.count("(pause)") == 1 and out.rstrip().endswith("(pause)")
    saved = Path(project.get_project_dir()) / "script" / "narration_directed.txt"
    assert saved.read_text(encoding="utf-8") == directed


def test_direct_narration_falls_back_to_the_script_when_the_directed_text_drifts(monkeypatch, env, caplog):
    from app.services import shorts_desk

    script = ("Ek raat Delhi mein Sudhansu ghar laut raha tha jab usne peeche se ek awaaz suni jo "
              "use bula rahi thi bar bar uske naam se.")
    directed = "Yeh ek bilkul alag kahani hai jiska upar wali script se koi lena dena nahi hai."
    monkeypatch.setattr(shorts_desk, "_agent_json", lambda *a, **k: {"text": directed})
    project = env.make_short()
    out = _REAL_DIRECT_NARRATION(script, "Raat3Baje", project=project)
    assert out == script
    # The directed attempt is still saved next to the script, for review.
    saved = Path(project.get_project_dir()) / "script" / "narration_directed.txt"
    assert saved.read_text(encoding="utf-8") == directed


def test_direct_narration_with_no_project_skips_the_save(monkeypatch, env):
    from app.services import shorts_desk

    monkeypatch.setattr(shorts_desk, "_agent_json", lambda *a, **k: {"text": "ek raat ki baat hai"})
    out = _REAL_DIRECT_NARRATION("ek raat ki baat hai", "Raat3Baje")
    assert out == "ek raat ki baat hai"


# --- durability: restarts (STUDIO_DIRECTOR_PLAN.md enhancement 2, Fable review rows 7-8) ---

def test_run_reel_reuses_the_narration_when_voice_style_and_text_match(env):
    """A reel re-run with the same script/voice/style (a retry after a
    restart, or after a failed render) must not re-synthesise narration
    already sitting on disk -- the same hash `run()` stores."""
    env.make_short()
    first = auto_story.run("reel_1")
    assert first["state"] == "packaged"
    assert len(env.calls["post"]) == 1

    second = auto_story.run("reel_1")
    assert second["state"] == "packaged"
    assert len(env.calls["post"]) == 1, "the narration must be reused, not re-synthesised"


def test_run_reel_persists_the_vibe_job_id_before_following_it(env, monkeypatch):
    """A Studio restart mid-render must find the job id on disk
    (`resume_watchers` reads `project.metadata['auto_story']['vibe_job_id']`)."""
    seen_job_ids = []
    real_follow = auto_story._follow_vibe_job

    def spying_follow(client, job_id, rec, say):
        on_disk = Project.load(rec["project_id"]).metadata["auto_story"]
        seen_job_ids.append(on_disk.get("vibe_job_id"))
        return real_follow(client, job_id, rec, say)

    monkeypatch.setattr(auto_story, "_follow_vibe_job", spying_follow)
    env.make_short()
    auto_story.run("reel_1")
    assert seen_job_ids == ["vibe1"]


class _FakeTime:
    """A stand-in for the `time` module, bound only inside `auto_story`'s own
    namespace for one test -- never the real process-wide clock."""

    def __init__(self):
        self.t = 0.0

    def time(self):
        return self.t


def test_follow_vibe_job_tolerates_a_few_misses_then_succeeds(monkeypatch):
    """A BuzzEdit restart answers connection errors for a few seconds until
    it is back up; `_follow_vibe_job` polls through that instead of raising
    on the very first miss."""
    monkeypatch.setattr(auto_story, "_sleep", lambda s: None)
    calls = {"n": 0}

    class FlakyClient:
        def vibe_reel_job(self, job_id):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("connection refused")
            return {"state": "done", "result": {"video": "x.mp4"}}

        def master_state(self):
            return {"paused": False}

    rec = {"project_id": "p1"}
    result = auto_story._follow_vibe_job(FlakyClient(), "job1", rec, lambda m: None)
    assert result == {"video": "x.mp4"}
    assert calls["n"] == 3


def test_follow_vibe_job_gives_up_after_the_miss_window(monkeypatch):
    """Still unreachable past `VIBE_FOLLOW_MISS_S`: give up with a clear
    error instead of polling forever."""
    fake_time = _FakeTime()
    monkeypatch.setattr(auto_story, "time", fake_time)
    monkeypatch.setattr(auto_story, "_sleep", lambda s: setattr(fake_time, "t", fake_time.t + s))
    monkeypatch.setattr(auto_story, "VIBE_FOLLOW_MISS_S", 60.0)
    monkeypatch.setattr(auto_story, "VIBE_POLL_S", 30.0)

    class DeadClient:
        def vibe_reel_job(self, job_id):
            raise RuntimeError("BuzzEdit restarted")

    rec = {"project_id": "p1"}
    with pytest.raises(RuntimeError, match="stopped answering"):
        auto_story._follow_vibe_job(DeadClient(), "job1", rec, lambda m: None)


def test_resume_watchers_reattaches_a_still_rendering_reel_job(env, monkeypatch):
    """A Studio restart mid-render: BuzzEdit still reports the job running,
    so `resume_watchers` re-attaches a follower instead of giving up."""
    project = env.make_short()
    pdir = Path(project.get_project_dir())
    stage = pdir / "production" / "vibe_reel"
    stage.mkdir(parents=True, exist_ok=True)
    video = stage / "reel.mp4"
    video.write_bytes(b"resumed video")
    rec = {"project_id": project.id, "channel": project.brand, "format": "rules_horror",
           "orientation": "vertical", "state": "rendering", "vibe_job_id": "vibe9",
           "started_at": "2026-10-24T01:00:00", "steps": [], "posted": {}, "final": None, "error": None}
    project.metadata["auto_story"] = rec
    project.save()

    # `resume_watchers`' own liveness check sees "running" (so it re-attaches
    # rather than giving up); the resumed follower's own poll then sees "done".
    calls = {"n": 0}

    def vibe_reel_job(self, job_id):
        assert job_id == "vibe9"
        calls["n"] += 1
        if calls["n"] == 1:
            return {"state": "running", "progress": 0.5, "message": "Scene 2/5 ready"}
        return {"state": "done", "progress": 1.0, "message": "Done",
                "result": {"video": str(video), "duration_s": 12.0}}

    monkeypatch.setattr(BuzzEditClient, "vibe_reel_job", vibe_reel_job)
    resumed = auto_story.resume_watchers()
    assert resumed == [project.id]
    auto_story._watchers[project.id].join(5.0)
    updated = Project.load(project.id).metadata["auto_story"]
    assert updated["state"] == "packaged"
    assert updated["final"] == str(pdir / "publish" / "instagram" / "reel.mp4")


def test_resume_watchers_marks_a_lost_reel_job_failed_for_retry(env, monkeypatch):
    """BuzzEdit no longer knows the job (it was never persisted there, or it
    is truly gone): the record is marked failed with a Retry hint rather
    than left stuck forever."""
    project = env.make_short()
    rec = {"project_id": project.id, "channel": project.brand, "format": "rules_horror",
           "orientation": "vertical", "state": "rendering", "vibe_job_id": "vibe9",
           "started_at": "2026-10-24T01:00:00", "steps": [], "posted": {}, "final": None, "error": None}
    project.metadata["auto_story"] = rec
    project.save()

    def vibe_reel_job(self, job_id):
        raise RuntimeError("Unknown job")

    monkeypatch.setattr(BuzzEditClient, "vibe_reel_job", vibe_reel_job)
    resumed = auto_story.resume_watchers()
    assert resumed == []
    updated = Project.load(project.id).metadata["auto_story"]
    assert updated["state"] == "failed"
    assert "press Retry" in updated["steps"][-1]["message"]


def test_resume_watchers_leaves_a_terminal_record_alone(env):
    project = env.make_short()
    rec = {"project_id": project.id, "channel": project.brand, "format": "rules_horror",
           "orientation": "vertical", "state": "failed", "error": "already failed",
           "started_at": "2026-10-24T01:00:00", "steps": [], "posted": {}, "final": None}
    project.metadata["auto_story"] = rec
    project.save()
    assert auto_story.resume_watchers() == []
    assert Project.load(project.id).metadata["auto_story"]["error"] == "already failed"


def test_fidelity_check_matches_a_devanagari_direction_against_its_roman_script():
    # 2026-10-24: the check compared Devanagari with Roman word for word, rejected every
    # directed text and narrated Roman Hinglish -- Hindi read like an English speaker.
    roman = "Kya aapko pata hai ki hamare bade-buzurgon ne raat ko nakhun na kaatne ki warning di thi"
    deva = "क्या आपको पता है कि हमारे बड़े-बुज़ुर्गों ने रात को नाखून न काटने की warning दी थी (pause)"
    overlap = auto_story._in_order_overlap(auto_story._content_words(roman), auto_story._content_words(deva))
    assert overlap >= auto_story.NARRATION_FIDELITY_MIN
    other = auto_story._in_order_overlap(auto_story._content_words(roman),
                                         auto_story._content_words("एक बिल्कुल अलग कहानी"))
    assert other < 0.3


def test_english_words_left_in_latin_are_written_in_devanagari(monkeypatch):
    import app.services.shorts_desk as shorts_desk
    seen = {}

    def fake(agent, task):
        seen["words"] = task["words"]
        return {"map": {"warning": "वॉर्निंग", "Hospital": "हॉस्पिटल", "pause": "पॉज़"}}

    monkeypatch.setattr(shorts_desk, "_agent_json", fake)
    out = auto_story.devanagari_english_words("यह warning थी। (pause) Hospital के बाहर।")
    assert out == "यह वॉर्निंग थी। (pause) हॉस्पिटल के बाहर।"
    assert seen["words"] == ["Hospital", "warning"]   # the cue is never sent


def test_devanagari_text_needs_no_model_call(monkeypatch):
    import app.services.shorts_desk as shorts_desk
    monkeypatch.setattr(shorts_desk, "_agent_json", lambda *a: (_ for _ in ()).throw(AssertionError("called")))
    assert auto_story.devanagari_english_words("सब देवनागरी में है।") == "सब देवनागरी में है।"


def test_delete_and_archive_record(env):
    project = env.make_short("story_delete_test")
    project.metadata["auto_story"] = {"state": "ready", "brand": "Raat3Baje", "format": "rules_horror"}
    project.save()

    # Verify initial list contains it and not archived
    records = auto_story.list_records()
    found = next((r for r in records if r["project_id"] == "story_delete_test"), None)
    assert found is not None
    assert found["archived"] is False

    # Archive it
    archived_rec = auto_story.archive_record("story_delete_test", archived=True)
    assert archived_rec["archived"] is True
    records_after_archive = auto_story.list_records()
    found_after = next((r for r in records_after_archive if r["project_id"] == "story_delete_test"), None)
    assert found_after["archived"] is True

    # Unarchive it
    unarchived_rec = auto_story.archive_record("story_delete_test", archived=False)
    assert unarchived_rec["archived"] is False

    # Delete it
    del_res = auto_story.delete_record("story_delete_test")
    assert del_res["status"] == "deleted"
    records_after_delete = auto_story.list_records()
    assert not any(r["project_id"] == "story_delete_test" for r in records_after_delete)

