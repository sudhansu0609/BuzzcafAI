"""
BuzzEdit voice conversion driven from the Studio (BuzzEdit VOICE_CHANGER_PLAN.md
brief S3): the story characters' speaker labels kept for BuzzEdit
(`integrations/script_reconcile.py`), the cast sheet's `voice` and its proposal
(`integrations/story_visuals.py`), the BuzzEditClient calls for the voices
library, the voice map and its job (HTTP mocked), the hook in
`app/api/produce_api.py` that converts the character lines before every render,
the routes behind the Projects page's cast block, and Dexter's voice actions.
No real BuzzEdit call is ever made: an unfaked call finds no BuzzEdit.
"""

import json
import logging
import os
import shutil

import pytest
import requests
from fastapi.testclient import TestClient

from app.api import produce_api
from app.main import app
from app.services import dexter_registry, produce_queue, strategist_runner
from core.models.project import Project
from integrations import buzzedit_client, story_visuals
from integrations.script_reconcile import (LABEL_LINE_RE, Reconciliation, clean_spoken_script,
                                          extract_vocabulary, script_speakers)

BUZZEDIT = "http://buzzedit.test"

VOICES = [{"name": "woman", "kind": "woman", "consent": "own", "created": "2026-10-09T10:00:00",
           "seconds": 12.0, "source": "woman.wav", "path": "C:/voices/woman.wav"},
          {"name": "demon", "kind": "demon", "consent": "own", "created": "2026-10-09T10:01:00",
           "seconds": 9.5, "source": "demon.wav", "path": "C:/voices/demon.wav"},
          {"name": "old_man", "kind": "man", "consent": "own", "created": "2026-10-09T10:02:00",
           "seconds": 15.0, "source": "old_man.wav", "path": "C:/voices/old_man.wav"}]


def _preset(name, voice, match_pitch, pitch_shift, steps):
    return {"name": name, "voice": voice, "voice_in_library": voice in ("woman", "demon"),
            "engine": {}, "fx": {}, "fx_rack": [],
            "params": {"preset": name, "match_pitch": match_pitch, "pitch_shift": pitch_shift,
                       "steps": steps, "cfg_rate": 0.7}}


PRESETS = {"engine_defaults": {"diffusion_steps": 25, "length_adjust": 1.0, "inference_cfg_rate": 0.7,
                               "f0_condition": False, "auto_f0_adjust": True, "pitch_shift": 0},
           "presets": {"Woman": _preset("Woman", "woman", True, 0, 25),
                       "Child": _preset("Child", "child", True, 4, 25),
                       "Demon": _preset("Demon", "demon", True, -5, 30),
                       "Monster": _preset("Monster", "demon", True, -7, 30),
                       "Ghost": _preset("Ghost", "woman", False, 0, 25)}}

CAST = {
    "world": "a deserted railway station at night, wet platforms, yellow sodium lamps",
    "main_character": "",
    "characters": [
        {"name": "Maya", "aliases": [], "gender": "female",
         "look": "a woman in her late twenties, slim, faded green sari, a red bindi"},
        {"name": "Chhotu", "aliases": ["the boy"], "look": "a thin 8-year-old boy in a torn school shirt"},
        {"name": "Kaala", "aliases": ["the thing in the yard"],
         "look": "a huge hunched creature with grey skin and long claws"},
        {"name": "Chudail", "aliases": ["the woman in white"],
         "look": "the spirit of a drowned bride, wet white sari, face hidden by long black hair"},
        {"name": "Ravi", "aliases": ["the guard"], "gender": "male",
         "look": "a man in his fifties, grey stubble, a khaki guard uniform"},
    ],
}

WOMAN = {"voice": "woman", "preset": "Woman", "match_pitch": True, "pitch_shift": 0, "steps": 25}
DEMON = {"voice": "demon", "preset": "Demon", "match_pitch": True, "pitch_shift": -5, "steps": 30}

# A Raat3Baje-style scene: the creator narrates, Maya and Ravi have lines.
SCRIPT = """# Station

Main us raat akela station par khada tha aur train bahut late thi.

MAYA: Tum yahan kya kar rahe ho itni raat ko?

VISUAL: An empty platform under a flickering lamp.

Maine use dekha aur kuch nahi bola.

RAVI (V.O.)
Woh ladki yahan pichhle saal mari thi.

**V.O. (Narrator):** Aur tab mujhe samajh aaya ki kuch theek nahi tha.
"""
SPOKEN = ("main us raat akela station par khada tha aur train bahut late thi "
          "tum yahan kya kar rahe ho itni raat ko "
          "maine use dekha aur kuch nahi bola "
          "woh ladki yahan pichhle saal mari thi "
          "aur tab mujhe samajh aaya ki kuch theek nahi tha")


def _words(text, programme=False):
    out = []
    for i, w in enumerate(text.split()):
        word = {"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4}
        if programme:
            word.update(tl_start=i * 0.5, tl_end=i * 0.5 + 0.4)
        out.append(word)
    return out


@pytest.fixture(autouse=True)
def no_real_buzzedit(monkeypatch):
    """Every BuzzEdit call a test does not fake answers "not reachable"."""
    monkeypatch.setattr(buzzedit_client, "base_url", lambda: None)


@pytest.fixture(autouse=True)
def isolated_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(produce_queue, "QUEUE_PATH", str(tmp_path / "produce_queue.json"))
    produce_queue.reset_for_tests()
    yield
    produce_queue.reset_for_tests()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def project():
    p = Project(id="voice_map_test_proj", name="Voice Map Probe", brand="Raat3Baje",
                workflow_name="after_dark_narration")
    p.metadata["buzzedit_project_id"] = "be_proj_1"
    p.save()
    yield p
    shutil.rmtree(p.get_project_dir(), ignore_errors=True)
    with produce_api._produce_lock:
        produce_api._produce_status.pop(p.id, None)


def _with_cast(project, cast=None):
    return story_visuals.save_cast_sheet(project, json.loads(json.dumps(cast or CAST)))


def _cast_with_voices(project, **voices):
    cast = json.loads(json.dumps(CAST))
    for person in cast["characters"]:
        if person["name"] in voices:
            person["voice"] = voices[person["name"]]
    return _with_cast(project, cast)


# --------------------------------------------------- speaker labels (reconcile)


def test_a_cast_characters_upper_case_line_is_their_spoken_dialogue():
    rec = Reconciliation(SCRIPT, _words(SPOKEN), speakers=["Maya", "Ravi"])
    by_first = {p.tokens[0]: p for p in rec.parsed.paragraphs}
    assert by_first["Tum"].speaker == "MAYA" and by_first["Tum"].label == "MAYA:"
    assert by_first["Tum"].tokens[:2] == ["Tum", "yahan"]                 # the label is not a word
    assert by_first["Woh"].speaker == "RAVI" and by_first["Woh"].label == "RAVI (V.O.)"
    assert by_first["Main"].speaker is None and by_first["Maine"].speaker is None
    assert by_first["Aur"].speaker is None                                # the narrator's label
    assert rec.speakers == ["MAYA", "RAVI"]
    tokens = " ".join(rec.parsed.tokens)
    assert "MAYA" not in tokens and "RAVI" not in tokens and "(V.O.)" not in tokens
    assert "VISUAL" not in tokens and "platform" not in tokens           # notes stay notes
    # Without the cast a `NAME:` line is a production note, as before; the
    # `NAME (V.O.)` cue is a speaker whatever the cast says.
    bare = Reconciliation(SCRIPT, _words(SPOKEN))
    assert "Tum" not in bare.parsed.tokens and bare.speakers == ["RAVI"]
    assert script_speakers(SCRIPT, ["maya"]) == ["MAYA", "RAVI"]          # case-insensitive


def test_render_writes_the_character_label_line_before_their_paragraph():
    rec = Reconciliation(SCRIPT, _words(SPOKEN), speakers=["Maya"])
    text = rec.render(speaker_labels=True)
    assert "\n\nMAYA:\nTum yahan kya kar rahe ho itni raat ko?\n\n" in text
    assert "\n\nRAVI (V.O.)\nWoh ladki yahan pichhle saal mari thi.\n\n" in text
    assert "Narrator" not in text and "V.O. (" not in text                # the narrator stays unlabelled
    assert [m.group(0) for m in LABEL_LINE_RE.finditer(text)] == ["MAYA:", "RAVI (V.O.)"]
    plain = rec.render()                                                  # the default: spoken words only
    assert "MAYA" not in plain and "RAVI" not in plain
    assert plain.replace("\n", " ").split() == text.replace("MAYA:", "").replace("RAVI (V.O.)", "").split()


def test_a_heading_inside_a_characters_paragraph_keeps_the_label_on_both_parts():
    rec = Reconciliation(SCRIPT, _words(SPOKEN), speakers=["Maya"])
    j = rec.words.index("kya")
    rec._headings[j] = "THE QUESTION"
    text = rec.render(speaker_labels=True)
    assert "MAYA:\nTum yahan\n\n# THE QUESTION\n\nMAYA:\nkya kar rahe ho" in text


def test_the_vocabulary_never_gets_the_label():
    cleaned = clean_spoken_script(SCRIPT, ["Maya", "Ravi"])
    assert "Tum yahan kya kar rahe ho itni raat ko?" in cleaned           # the dialogue is spoken
    vocabulary = extract_vocabulary(cleaned)
    assert "MAYA" not in vocabulary and "RAVI" not in vocabulary
    assert "Narrator" not in vocabulary and "VISUAL" not in vocabulary
    assert "yahan" in vocabulary and "ladki" in vocabulary


def test_story_timing_does_not_count_a_label_line_as_a_word(monkeypatch):
    rec = Reconciliation(SCRIPT, _words(SPOKEN, programme=True), speakers=["Maya"])
    rec.place_transcript_beat({"kind": "broll_image", "anchor": "woh ladki yahan",
                               "image_prompt": "an old photograph of a girl"})
    text = rec.render(speaker_labels=True)
    seen = {}
    real = story_visuals.plan_timed_shots

    def capture(anchors, word_starts, *args, **kwargs):
        seen["anchors"], seen["starts"] = list(anchors), list(word_starts)
        return real(anchors, word_starts, *args, **kwargs)

    monkeypatch.setattr(story_visuals, "plan_timed_shots", capture)
    out, stats = story_visuals.apply_to_script(text, 0.0, CAST, word_times=rec.word_times,
                                               duration_s=rec.duration_s, image_share=1.0)
    # Every spoken word keeps its own programme time: the labels were not counted.
    assert seen["starts"] == rec.word_times and len(seen["starts"]) == len(SPOKEN.split())
    assert seen["anchors"] == [SPOKEN.split().index("woh")]               # the picture sits on "Woh"
    assert "MAYA:\n" in out and "RAVI (V.O.)\n" in out and stats["pictures"] == 1


# ------------------------------------------------------ cast voices + proposal


def test_propose_voices_uses_only_the_library():
    cast = story_visuals.propose_voices(CAST, VOICES, PRESETS)
    voices = {p["name"]: p["voice"] for p in cast["characters"]}
    assert voices["Maya"] == WOMAN
    assert voices["Chhotu"] is None                                       # no child voice in the library
    assert voices["Kaala"] == {"voice": "demon", "preset": "Monster", "match_pitch": True,
                                 "pitch_shift": -7, "steps": 30}         # creature -> Monster
    assert voices["Chudail"] == {"voice": "woman", "preset": "Ghost", "match_pitch": False,
                                 "pitch_shift": 0, "steps": 25}          # the dead -> Ghost
    assert voices["Ravi"] == {"voice": "old_man", "preset": None, "match_pitch": False,
                              "pitch_shift": 0, "steps": 25}            # man -> a male library voice
    # A demon's own word wins over "creature"; a child's voice once the library has one.
    demon = dict(CAST["characters"][2], name="Brahmarakshas")
    child_voice = VOICES + [{"name": "kid_ref", "kind": "child"}]
    kids = story_visuals.propose_voices({"characters": [demon, CAST["characters"][1]]}, child_voice, PRESETS)
    assert kids["characters"][0]["voice"]["preset"] == "Demon"
    assert kids["characters"][1]["voice"] == {"voice": "kid_ref", "preset": "Child", "match_pitch": True,
                                              "pitch_shift": 4, "steps": 25}


def test_propose_voices_with_an_empty_library_leaves_every_voice_none():
    for library in ([], {"voices": []}, None):
        cast = story_visuals.propose_voices(CAST, library, PRESETS)
        assert [p["voice"] for p in cast["characters"]] == [None] * len(CAST["characters"])
    male_only = story_visuals.propose_voices(CAST, [{"name": "old_man", "kind": "man"}], {})
    assert [p["name"] for p in male_only["characters"] if p["voice"]] == ["Ravi"]


def test_the_cast_sheet_keeps_a_voice_decided_or_not(project):
    stored = _cast_with_voices(project, Maya=dict(WOMAN, pitch_shift=40, steps=2), Ravi=None)
    again = story_visuals.load_cast_sheet(project)
    assert again == stored
    people = {p["name"]: p for p in again["characters"]}
    assert people["Maya"]["voice"] == dict(WOMAN, pitch_shift=12, steps=10)   # clamped to BuzzEdit's ranges
    assert "voice" in people["Ravi"] and people["Ravi"]["voice"] is None     # decided: his own voice
    assert "voice" not in people["Chhotu"]                                   # never proposed
    assert story_visuals.voices_decided(again) and not story_visuals.voices_decided(CAST)
    assert story_visuals.character_names(again) == ["Maya", "Chhotu", "Kaala", "Chudail", "Ravi"]


def test_the_voice_map_uses_the_scripts_spelling_and_warns_about_silent_characters():
    cast = json.loads(json.dumps(CAST))
    cast["characters"][0]["voice"] = WOMAN
    cast["characters"][2]["voice"] = DEMON
    cast["characters"][4]["voice"] = None
    voice_map, warnings = story_visuals.voice_map_for(cast, ["MAYA", "RAVI (V.O.)"])
    assert voice_map == {"MAYA": WOMAN}
    assert len(warnings) == 1 and warnings[0].startswith("Kaala has a voice but never speaks")
    voice_map, _ = story_visuals.voice_map_for({"characters": [dict(CAST["characters"][4], voice=DEMON)]},
                                               ["RAVI (V.O.)"])
    assert voice_map == {"RAVI": DEMON}                                   # "(V.O.)" dropped
    nothing, silent = story_visuals.voice_map_for(cast, [])
    assert nothing == {} and len(silent) == 2                            # Maya and Kaala; Ravi has none


# ----------------------------------------------------------- the client (HTTP)


class _FakeHTTP:
    """`requests.request`, answering from a table of answer lists (the last
    one repeats) and keeping every call."""

    def __init__(self, answers):
        self.answers = {key: list(value) if isinstance(value, list) else [value]
                        for key, value in answers.items()}
        self.calls = []

    def __call__(self, method, url, timeout=None, **kwargs):
        path = url[len(BUZZEDIT):]
        self.calls.append((method, path, kwargs.get("json")))
        queue = self.answers[(method, path)]
        status, body = queue.pop(0) if len(queue) > 1 else queue[0]
        resp = requests.Response()
        resp.status_code = status
        resp._content = json.dumps(body).encode("utf-8")
        resp.headers["Content-Type"] = "application/json"
        resp.url = url
        return resp


@pytest.fixture
def http(monkeypatch):
    def install(answers):
        fake = _FakeHTTP(answers)
        monkeypatch.setattr(buzzedit_client, "base_url", lambda: BUZZEDIT)
        monkeypatch.setattr(buzzedit_client.requests, "request", fake)
        return fake
    return install


def test_the_client_reads_the_library_presets_and_speakers(http, caplog):
    spans = {"has_script": True, "speakers": ["MAYA"],
             "spans": [{"speaker": "MAYA", "start_s": 6.0, "end_s": 10.0, "text": "Tum yahan"}]}
    fake = http({("GET", "/api/audio/voices"): (200, {"voices": VOICES}),
                 ("GET", "/api/audio/voice/presets"): (200, PRESETS),
                 ("GET", "/api/audio/be_proj_1/speaker_spans"): (200, spans)})
    c = buzzedit_client.BuzzEditClient()
    assert c.list_voices() == VOICES
    assert c.voice_presets() == PRESETS
    assert c.speaker_spans("be_proj_1") == spans
    assert fake.calls == [("GET", "/api/audio/voices", None), ("GET", "/api/audio/voice/presets", None),
                          ("GET", "/api/audio/be_proj_1/speaker_spans", None)]

    http({("GET", "/api/audio/voices"): (404, {"detail": "Not Found"})})          # an older BuzzEdit
    with caplog.at_level(logging.WARNING, logger="buzzcaf_ai.buzzedit_client"):
        assert buzzedit_client.BuzzEditClient().list_voices() is None
    assert "Could not list BuzzEdit's voices library" in caplog.text


def test_the_client_sends_the_map_starts_the_job_and_stops_the_worker(http, caplog):
    fake = http({("PUT", "/api/audio/be_proj_1/voice_map"): (200, {"voice_map": {"MAYA": WOMAN}}),
                 ("POST", "/api/audio/be_proj_1/voice/apply_map"): (200, {"job_id": "audio_process_1"}),
                 ("POST", "/api/audio/voice/worker/stop"): (200, {"running": False, "device": None,
                                                                   "idle_s": None})})
    c = buzzedit_client.BuzzEditClient()
    assert c.put_voice_map("be_proj_1", {"MAYA": WOMAN}) == {"voice_map": {"MAYA": WOMAN}}
    assert c.apply_voice_map("be_proj_1") == "audio_process_1"
    assert c.stop_voice_worker()["running"] is False
    assert fake.calls == [("PUT", "/api/audio/be_proj_1/voice_map", {"voice_map": {"MAYA": WOMAN}}),
                          ("POST", "/api/audio/be_proj_1/voice/apply_map", {}),
                          ("POST", "/api/audio/voice/worker/stop", {})]

    http({("PUT", "/api/audio/be_proj_1/voice_map"):
          (422, {"detail": "voice_map['MAYA']: Voice 'gone' is not in the voices library"}),
          ("POST", "/api/audio/be_proj_1/voice/apply_map"): (503, {"detail": "seed-vc engine unavailable"})})
    with caplog.at_level(logging.WARNING, logger="buzzcaf_ai.buzzedit_client"):
        assert c.put_voice_map("be_proj_1", {"MAYA": {"voice": "gone"}}) is None
        assert c.apply_voice_map("be_proj_1") is None
    assert "Voice 'gone' is not in the voices library" in caplog.text
    assert "seed-vc engine unavailable" in caplog.text


def test_wait_job_follows_the_job_to_the_end(http, monkeypatch):
    monkeypatch.setattr(buzzedit_client.time, "sleep", lambda s: None)
    path = "/api/audio/be_proj_1/process/audio_process_1"
    done = {"id": "audio_process_1", "status": "completed", "progress": 1.0, "message": "done",
            "result": {"voice_conversions": [{"speaker": "MAYA", "voice": "woman", "spans": [[6.0, 10.0]],
                                              "seconds": 4.0}], "failed_spans": []}, "error": None}
    http({("GET", path): [(200, {"status": "pending", "progress": 0.0, "message": "queued"}),
                          (200, {"status": "running", "progress": 0.3, "message": "MAYA -> woman (1/2)"}),
                          (500, {"detail": "busy"}),                       # one bad poll is not the end
                          (200, {"status": "running", "progress": 0.7, "message": "MAYA -> woman (2/2)"}),
                          (200, done)]})
    seen = []
    job = buzzedit_client.BuzzEditClient().wait_job("be_proj_1", "audio_process_1",
                                                    progress_cb=lambda f, m: seen.append((f, m)))
    assert job == done
    assert seen == [(0.0, "queued"), (0.3, "MAYA -> woman (1/2)"), (0.7, "MAYA -> woman (2/2)")]

    http({("GET", path): (200, {"status": "failed", "progress": 0.1, "error": "seed-vc crashed"})})
    assert buzzedit_client.BuzzEditClient().wait_job("be_proj_1", "audio_process_1")["error"] == "seed-vc crashed"
    http({("GET", path): (404, {"detail": "No audio process job"})})        # BuzzEdit restarted
    assert buzzedit_client.BuzzEditClient().wait_job("be_proj_1", "audio_process_1") is None


def test_wait_job_gives_up_only_on_a_stall(http, monkeypatch):
    clock = {"t": 0.0}

    def tick():
        clock["t"] += 60.0
        return clock["t"]

    monkeypatch.setattr(buzzedit_client.time, "sleep", lambda s: None)
    monkeypatch.setattr(buzzedit_client.time, "monotonic", tick)
    path = "/api/audio/be_proj_1/process/audio_process_1"
    http({("GET", path): (200, {"status": "running", "progress": 0.5, "message": "MAYA -> woman (3/9)"})})
    # Hours of polls with the job alive would not end it; 30 minutes of the same
    # progress and message does.
    assert buzzedit_client.BuzzEditClient().wait_job("be_proj_1", "audio_process_1") is None
    assert 30 * 60 < clock["t"] < 60 * 60


def test_the_client_answers_none_when_buzzedit_is_not_running(caplog):
    c = buzzedit_client.BuzzEditClient()
    with caplog.at_level(logging.WARNING, logger="buzzcaf_ai.buzzedit_client"):
        assert c.list_voices() is None and c.voice_presets() is None
        assert c.speaker_spans("be_proj_1") is None and c.put_voice_map("be_proj_1", {}) is None
        assert c.apply_voice_map("be_proj_1") is None and c.stop_voice_worker() is None
    assert caplog.text.count("not reachable") == 6


# ------------------------------------------------------------ the render hook


class _FakeVoiceClient:
    """The BuzzEditClient voice calls, recorded in order."""

    def __init__(self, voices=VOICES, speakers=("MAYA",), job="completed", order=None):
        self.voices, self.speakers, self.job = voices, list(speakers), job
        self.order = order if order is not None else []
        self.sent_map = None

    def list_voices(self):
        self.order.append("list_voices")
        return self.voices

    def voice_presets(self):
        self.order.append("voice_presets")
        return PRESETS

    def speaker_spans(self, project_id):
        self.order.append(("speaker_spans", project_id))
        return {"has_script": True, "speakers": self.speakers, "spans": []}

    def put_voice_map(self, project_id, voice_map):
        self.order.append(("put_voice_map", project_id))
        self.sent_map = voice_map
        return {"voice_map": voice_map}

    def apply_voice_map(self, project_id):
        self.order.append(("apply_voice_map", project_id))
        return "audio_process_7"

    def wait_job(self, project_id, job_id, timeout_s=None, progress_cb=None, **_):
        self.order.append(("wait_job", job_id, timeout_s))
        if progress_cb:
            progress_cb(0.5, "MAYA -> woman (1/2)")
        if self.job is None:
            return None
        if self.job == "failed":
            return {"status": "failed", "error": "seed-vc crashed"}
        return {"status": "completed", "result": {
            "voice_conversions": [{"speaker": s, "voice": (self.sent_map or {}).get(s, {}).get("voice"),
                                   "spans": [[6.0, 10.0]], "seconds": 4.0} for s in self.sent_map or {}],
            "failed_spans": [{"speaker": "MAYA", "voice": "woman", "span": [20.0, 21.0], "error": "boom"}]}}

    def stop_voice_worker(self):
        self.order.append("stop_voice_worker")
        return {"running": False}


def test_the_hook_builds_the_map_waits_for_the_job_and_records_the_report(project):
    _cast_with_voices(project, Maya=WOMAN, Kaala=DEMON, Ravi=None)
    fake = _FakeVoiceClient(speakers=["MAYA", "RAVI"])
    report = produce_api.apply_voice_map_to_buzzedit(project, fake, "be_proj_1")
    assert fake.sent_map == {"MAYA": WOMAN}                               # Ravi keeps his own voice
    assert fake.order == ["list_voices", ("speaker_spans", "be_proj_1"), ("put_voice_map", "be_proj_1"),
                          ("apply_voice_map", "be_proj_1"), ("wait_job", "audio_process_7", None),
                          "stop_voice_worker"]                            # no timeout; the GPU freed
    assert report["voice_map"] == {"MAYA": WOMAN} and report["note"] is None
    assert report["voice_conversions"] == [{"speaker": "MAYA", "voice": "woman", "spans": [[6.0, 10.0]],
                                            "seconds": 4.0}]
    assert report["failed_spans"][0]["error"] == "boom"
    assert len(report["warnings"]) == 1 and report["warnings"][0].startswith("Kaala has a voice")
    meta = Project.load(project.id).metadata
    assert meta["voice_conversions"] == report["voice_conversions"]
    assert meta["voice_map"] == {"MAYA": WOMAN} and meta["voice_report"] == report
    status = produce_api._get_status(project.id)
    assert status["voice_conversions"] == report["voice_conversions"] and status["voice_report"] == report


def test_the_hook_proposes_voices_once_when_none_was_ever_set(project):
    _with_cast(project)
    fake = _FakeVoiceClient(speakers=["MAYA", "KAALA"])
    report = produce_api.apply_voice_map_to_buzzedit(project, fake, "be_proj_1")
    assert "voice_presets" in fake.order
    assert set(report["proposed"]) == {"Maya", "Kaala", "Chudail", "Ravi"}
    assert fake.sent_map == {"MAYA": WOMAN, "KAALA": {"voice": "demon", "preset": "Monster", "match_pitch": True,
                                                        "pitch_shift": -7, "steps": 30}}
    saved = {p["name"]: p for p in story_visuals.load_cast_sheet(project)["characters"]}
    assert saved["Maya"]["voice"] == WOMAN and saved["Chhotu"]["voice"] is None
    # Decided now: the next production uses the cast as it is.
    again = _FakeVoiceClient(speakers=["MAYA"])
    produce_api.apply_voice_map_to_buzzedit(project, again, "be_proj_1")
    assert "voice_presets" not in again.order and again.sent_map == {"MAYA": WOMAN}


def test_the_hook_skips_cleanly_when_no_character_has_a_voice(project):
    _cast_with_voices(project, Maya=None, Chhotu=None, Kaala=None, Chudail=None, Ravi=None)
    project.metadata["voice_conversions"] = [{"speaker": "OLD", "voice": "x", "spans": [], "seconds": 1}]
    project.metadata["voice_map"] = {"OLD": WOMAN}
    project.save()
    fake = _FakeVoiceClient(speakers=["MAYA"])
    report = produce_api.apply_voice_map_to_buzzedit(project, fake, "be_proj_1")
    assert report["note"] == produce_api.VOICE_NOTE_NO_VOICE
    assert fake.order == ["list_voices", ("speaker_spans", "be_proj_1")]  # nothing sent, no job
    meta = Project.load(project.id).metadata
    assert "voice_conversions" not in meta and "voice_map" not in meta  # not last run's
    assert meta["voice_report"]["note"] == "no character has a voice"


def test_the_hook_notes_an_empty_library_and_a_script_without_character_lines(project):
    _cast_with_voices(project, Maya=WOMAN)
    empty = _FakeVoiceClient(voices=[])
    report = produce_api.apply_voice_map_to_buzzedit(project, empty, "be_proj_1")
    assert report["note"] == "no voices in the library" and empty.order == ["list_voices"]

    narration = _FakeVoiceClient(speakers=[])                             # "my style": no labels
    report = produce_api.apply_voice_map_to_buzzedit(project, narration, "be_proj_1")
    assert report["note"] == "script has no character lines"
    assert narration.sent_map is None and "stop_voice_worker" not in narration.order


def test_a_failed_conversion_is_noted_and_the_worker_still_stops(project):
    _cast_with_voices(project, Maya=WOMAN)
    for outcome, note in (("failed", "voice conversion failed: seed-vc crashed"),
                          (None, "BuzzEdit's voice conversion did not finish (see the log)")):
        fake = _FakeVoiceClient(job=outcome)
        report = produce_api.apply_voice_map_to_buzzedit(project, fake, "be_proj_1")
        assert report["note"] == note and report["voice_conversions"] == []
        assert fake.order[-1] == "stop_voice_worker"
        assert report["voice_map"] == {"MAYA": WOMAN}
        assert "voice_conversions" not in Project.load(project.id).metadata


def test_the_hook_records_nothing_without_a_cast_or_an_edit(project):
    fake = _FakeVoiceClient()
    assert produce_api.apply_voice_map_to_buzzedit(project, fake, "be_proj_1") is None
    _cast_with_voices(project, Maya=WOMAN)
    assert produce_api.apply_voice_map_to_buzzedit(project, fake, None) is None
    assert fake.order == []
    assert "voice_report" not in Project.load(project.id).metadata
    assert produce_api._get_status(project.id)["voice_report"] is None


def _kept_words(text):
    return [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate(text.split())]


def test_a_story_production_converts_the_character_lines_before_the_render(monkeypatch, project):
    """Straight through `_plan_and_render` for a Raat3Baje story (no review
    gate), BuzzEdit faked: the script BuzzEdit gets labels Maya's line, her
    voice map goes over and its job finishes before the render is enqueued,
    and the finished run reports the conversion."""
    script_dir = os.path.join(project.get_project_dir(), "script")
    os.makedirs(script_dir, exist_ok=True)
    with open(os.path.join(script_dir, "script.md"), "w", encoding="utf-8") as f:
        f.write(SCRIPT)
    project.assets["script"] = "script/script.md"
    project.metadata["video_settings"] = {"review_mode": "none"}
    project.save()
    _cast_with_voices(project, Maya=WOMAN, Ravi=None)

    order, sent = [], {}
    fake = _FakeVoiceClient(order=order)

    def set_script(self, pid, text):
        sent["script"] = text
        return {"ok": True}

    def speaker_spans(self, pid):
        # BuzzEdit reads the speakers from the labels of the script it was handed.
        order.append(("speaker_spans", pid))
        names = [m.group(0).rstrip(":").replace("(V.O.)", "").strip()
                 for m in LABEL_LINE_RE.finditer(sent.get("script", ""))]
        return {"has_script": True, "speakers": names, "spans": []}

    for name in ("list_voices", "voice_presets", "put_voice_map", "apply_voice_map", "wait_job",
                 "stop_voice_worker"):
        monkeypatch.setattr(produce_api.BuzzEditClient, name,
                            lambda self, *a, _n=name, **k: getattr(fake, _n)(*a, **k))
    monkeypatch.setattr(produce_api.BuzzEditClient, "speaker_spans", speaker_spans)
    monkeypatch.setattr(produce_api.BuzzEditClient, "set_script", set_script)
    monkeypatch.setattr(produce_api.BuzzEditClient, "get_kept_words", lambda self, pid: _kept_words(SPOKEN))
    monkeypatch.setattr(produce_api, "plan_visual_windows", lambda *a, **k: {
        "beats": [{"kind": "broll_image", "anchor": "woh ladki yahan", "start": 1.0, "end": 2.0,
                   "window_index": 0, "prompt": "an old photograph", "image_prompt": "an old photograph"}],
        "windows": 1, "ok": 1, "failed": []})
    monkeypatch.setattr(produce_api.BuzzEditClient, "enqueue_presentation",
                        lambda self, pid, settings, start_at="": order.append("enqueue") or {"job": {"id": "job_1"}})
    monkeypatch.setattr(produce_api.BuzzEditClient, "get_jobs",
                        lambda self: {"jobs": [{"id": "job_1", "status": "completed", "progress": 1.0}]})
    monkeypatch.setattr(produce_api.BuzzEditClient, "get_report", lambda self, pid: {"output_path": "/out/v.mp4"})
    monkeypatch.setattr(produce_api, "_free_gpu_for_render", lambda project_id: None)

    produce_api._plan_and_render(project.id, "script_first", None, False)

    status = produce_api._get_status(project.id)
    assert status["state"] == "ready"
    assert "\nMAYA:\n" in sent["script"] and "\nRAVI (V.O.)\n" in sent["script"]
    assert "Narrator" not in sent["script"]
    assert fake.sent_map == {"MAYA": WOMAN}
    assert order.index(("put_voice_map", "be_proj_1")) < order.index("stop_voice_worker") < order.index("enqueue")
    assert status["voice_conversions"] == [{"speaker": "MAYA", "voice": "woman", "spans": [[6.0, 10.0]],
                                            "seconds": 4.0}]
    assert Project.load(project.id).metadata["voice_conversions"] == status["voice_conversions"]


# -------------------------------------------------- Projects page and Dexter


def _fake_library(monkeypatch, voices=VOICES):
    monkeypatch.setattr(produce_api.BuzzEditClient, "list_voices", lambda self: voices)
    monkeypatch.setattr(produce_api.BuzzEditClient, "voice_presets", lambda self: PRESETS)


def test_the_projects_page_reads_the_library_and_the_cast(client, monkeypatch, project):
    _fake_library(monkeypatch)
    body = client.get("/api/produce/voices").json()
    assert body["available"] is True and [v["name"] for v in body["voices"]] == ["woman", "demon", "old_man"]
    assert set(body["presets"]) == {"Woman", "Child", "Demon", "Monster", "Ghost"}
    monkeypatch.setattr(produce_api.BuzzEditClient, "list_voices", lambda self: None)
    assert client.get("/api/produce/voices").json() == {"available": False, "voices": [], "presets": {},
                                                        "engine_defaults": {}}

    assert client.get(f"/api/projects/{project.id}/cast").json()["characters"] == []   # no sheet yet
    _cast_with_voices(project, Maya=WOMAN)
    cast = client.get(f"/api/projects/{project.id}/cast").json()
    people = {p["name"]: p for p in cast["characters"]}
    assert people["Maya"]["voice"] == WOMAN and people["Maya"]["voice_set"] is True
    assert people["Ravi"]["voice"] is None and people["Ravi"]["voice_set"] is False
    assert cast["voices_decided"] is True and cast["buzzedit_project_id"] == "be_proj_1"
    assert client.get("/api/projects/no_such_project/cast").status_code == 404


def test_the_projects_page_sets_and_proposes_voices(client, monkeypatch, project):
    url = f"/api/projects/{project.id}/cast/voice"
    _fake_library(monkeypatch)
    assert client.put(url, json={"character": "Maya", "preset": "Woman"}).status_code == 404   # no cast yet
    _with_cast(project)
    body = client.put(url, json={"character": "maya", "preset": "Woman"}).json()
    assert {p["name"]: p["voice"] for p in body["characters"]}["Maya"] == WOMAN       # the preset's own clip
    body = client.put(url, json={"character": "Ravi", "voice": "OLD_MAN"}).json()
    assert {p["name"]: p["voice"] for p in body["characters"]}["Ravi"] == {
        "voice": "old_man", "preset": None, "match_pitch": False, "pitch_shift": 0, "steps": 25}
    body = client.put(url, json={"character": "Kaala", "voice": "demon", "preset": "Monster"}).json()
    assert {p["name"]: p["voice"] for p in body["characters"]}["Kaala"] == {
        "voice": "demon", "preset": "Monster", "match_pitch": True, "pitch_shift": -7, "steps": 30}
    body = client.put(url, json={"character": "Maya", "voice": None, "preset": None}).json()
    maya = next(p for p in body["characters"] if p["name"] == "Maya")
    assert maya["voice"] is None and maya["voice_set"] is True                        # her own voice
    assert client.put(url, json={"character": "Chhotu", "preset": "Child"}).status_code == 422  # no child clip
    assert client.put(url, json={"character": "Maya", "voice": "nobody"}).status_code == 422
    assert client.put(url, json={"character": "Maya", "preset": "Robot"}).status_code == 422
    assert client.put(url, json={"character": "Nobody", "voice": "woman"}).status_code == 404
    monkeypatch.setattr(produce_api.BuzzEditClient, "list_voices", lambda self: None)
    assert client.put(url, json={"character": "Maya", "voice": "woman"}).status_code == 502

    propose = f"/api/projects/{project.id}/cast/propose_voices"
    assert client.post(propose).status_code == 502
    _fake_library(monkeypatch, voices=[])
    resp = client.post(propose)
    assert resp.status_code == 409 and "No voices in the library" in resp.json()["detail"]
    _fake_library(monkeypatch)
    body = client.post(propose).json()
    assert body["proposed"]["Maya"] == WOMAN and body["proposed"]["Chhotu"] is None
    assert {p["name"]: p["voice"] for p in story_visuals.load_cast_sheet(project)["characters"]}["Maya"] == WOMAN


def test_dexter_reads_voices_and_sets_a_characters_voice(monkeypatch, project):
    _fake_library(monkeypatch)
    _cast_with_voices(project, Maya=WOMAN)
    voices = dexter_registry.invoke("voices", {})
    assert voices["status"] == "success" and voices["kind"] == "read"
    assert [v["name"] for v in voices["result"]["voices"]] == ["woman", "demon", "old_man"]

    vmap = dexter_registry.invoke("voice_map_of_project", {"project": project.id})
    assert vmap["status"] == "success" and vmap["result"]["characters"]["Maya"] == WOMAN
    assert vmap["result"]["characters"]["Ravi"] is None and vmap["result"]["last_voice_map"] is None

    meta = Project.load(project.id)
    meta.metadata["voice_conversions"] = [{"speaker": "MAYA", "voice": "woman", "spans": [[6.0, 10.0]],
                                           "seconds": 4.0}]
    meta.metadata["voice_report"] = {"note": None, "warnings": []}
    meta.save()
    conv = dexter_registry.invoke("voice_conversions_of_project", {"project": project.id})
    assert conv["status"] == "success" and conv["result"]["voice_conversions"][0]["speaker"] == "MAYA"

    done = dexter_registry.invoke("set_character_voice", {"project": project.id, "character": "Kaala",
                                                          "preset": "Demon"})
    assert done["status"] == "success" and done["kind"] == "write"
    assert {p["name"]: p["voice"] for p in done["result"]["characters"]}["Kaala"] == DEMON
    assert dexter_registry.invoke("set_character_voice", {"project": project.id, "character": "Maya"})["code"] == 422
    assert dexter_registry.invoke("set_character_voice", {"project": project.id, "voice": "woman"})["code"] == 422
    assert dexter_registry.invoke("set_character_voice", {"project": project.id, "character": "Maya",
                                                          "voice": "nobody"})["code"] == 422
    assert dexter_registry.invoke("voice_map_of_project", {"project": "no_such_project"})["code"] == 404


def test_the_voice_actions_are_reads_plus_one_safe_write_and_no_delete():
    voice = {c["name"]: c["kind"] for c in dexter_registry.CAPABILITIES if c["domain"] == "voice"}
    assert voice == {"voices": "read", "voice_map_of_project": "read", "voice_conversions_of_project": "read",
                     "set_character_voice": "write"}
    unattended = {a["name"] for a in strategist_runner.allowed_actions()}
    assert set(voice) <= unattended
    assert not any("delete" in c["name"] and "voice" in c["name"] for c in dexter_registry.CAPABILITIES)
