"""
BuzzEdit audio racks driven from the Studio (BuzzEdit AUDIO_SUITE_PLAN.md
brief A5): the per-channel `audio_rack_preset` setting, the BuzzEditClient
calls for BuzzEdit's rack presets (HTTP mocked), the hook in
`app/api/produce_api.py` that puts a channel's preset on the A1 rack before
every render, the routes behind the Projects page, and Dexter's audio actions.
No real BuzzEdit call is ever made: an unfaked call finds no BuzzEdit.
"""

import json
import logging
import shutil

import pytest
import requests
from fastapi.testclient import TestClient

from app.api import produce_api
from app.main import app
from app.services import dexter_registry, produce_queue, strategist_runner
from core.models.project import Project
from integrations import buzzedit_client

BUZZEDIT = "http://buzzedit.test"
PODCAST_RACK = {"audio_rack_preset": "Podcast", "scope": "A1", "effects": ["parametric_eq", "deesser"]}


@pytest.fixture
def client():
    return TestClient(app)


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
def project():
    p = Project(id="audio_rack_test_proj", name="Audio Rack Probe", brand="Life3Baje",
                workflow_name="life3baje_video")
    p.metadata["buzzedit_project_id"] = "be_proj_1"
    p.save()
    yield p
    shutil.rmtree(p.get_project_dir(), ignore_errors=True)
    with produce_api._produce_lock:
        produce_api._produce_status.pop(p.id, None)


def _channels(monkeypatch, table):
    """The Studio settings with `audio_rack_preset` = `table`."""
    real = produce_api.load_llm_config
    monkeypatch.setattr(produce_api, "load_llm_config", lambda: {**real(), "audio_rack_preset": table})


def _fake_apply(monkeypatch, order=None):
    calls = []

    def apply(self, project_id, scope, name):
        calls.append((project_id, scope, name))
        if order is not None:
            order.append(("apply", scope, name))
        return {"scope": scope, "revision": 7, "effects": [
            {"id": "fx_0", "effect": "parametric_eq"}, {"id": "fx_1", "effect": "deesser"}]}

    monkeypatch.setattr(produce_api.BuzzEditClient, "apply_rack_preset", apply)
    return calls


# ------------------------------------------------------------------ the setting


def test_the_audio_rack_preset_setting_round_trips(client, tmp_path, monkeypatch):
    # Settings write the config file: point it at a scratch one.
    import integrations.llm as llm_module
    monkeypatch.setattr(llm_module, "CONFIG_PATH", str(tmp_path / "config.json"))
    assert "audio_rack_preset" not in client.get("/api/settings").json()      # default: none

    table = {"Raat3Baje": "Podcast", "Life3Baje": "Warm voice"}
    assert client.post("/api/settings", json={"audio_rack_preset": table}).status_code == 200
    assert client.get("/api/settings").json()["audio_rack_preset"] == table
    assert json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))["audio_rack_preset"] == table

    # The page sends the whole table: a channel left out has no preset again.
    client.post("/api/settings", json={"audio_rack_preset": {"Raat3Baje": "Podcast"}})
    assert client.get("/api/settings").json()["audio_rack_preset"] == {"Raat3Baje": "Podcast"}
    assert client.post("/api/settings", json={"audio_rack_preset": ["Podcast"]}).status_code == 422


def test_a_channels_preset_is_found_the_way_brands_match(monkeypatch):
    _channels(monkeypatch, {"Raat 3 Baje": " Podcast ", "Life3Baje": "  ", "Khayal3Baje": None})
    assert produce_api.audio_rack_preset_for("Raat3Baje") == "Podcast"
    assert produce_api.audio_rack_preset_for("raat3baje") == "Podcast"
    assert produce_api.audio_rack_preset_for("Life3Baje") is None             # blank = none
    assert produce_api.audio_rack_preset_for("Khayal3Baje") is None
    assert produce_api.audio_rack_preset_for("Beyond3Baje") is None
    assert produce_api.audio_rack_preset_for("") is None
    monkeypatch.setattr(produce_api, "load_llm_config", lambda: {})
    assert produce_api.audio_rack_preset_for("Raat3Baje") is None


# ----------------------------------------------------------- the client (HTTP)


class _FakeHTTP:
    """`requests.request`, answering from a table and keeping every call."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, method, url, timeout=None, **kwargs):
        path = url[len(BUZZEDIT):]
        self.calls.append((method, path, kwargs.get("json")))
        status, body = self.answers[(method, path)]
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


def test_the_client_lists_buzzedits_rack_presets(http, caplog):
    presets = {"Podcast": {"effects": [{"id": "fx_1", "effect": "parametric_eq"}],
                           "created": "2026-10-09T10:00:00", "note": ""}}
    fake = http({("GET", "/api/audio/rack_presets"): (200, {"presets": presets})})
    assert buzzedit_client.BuzzEditClient().list_rack_presets() == presets
    assert fake.calls == [("GET", "/api/audio/rack_presets", None)]

    http({("GET", "/api/audio/rack_presets"): (404, {"detail": "Not Found"})})     # an older BuzzEdit
    with caplog.at_level(logging.WARNING, logger="buzzcaf_ai.buzzedit_client"):
        assert buzzedit_client.BuzzEditClient().list_rack_presets() is None
    assert "Could not list BuzzEdit's audio rack presets" in caplog.text


def test_the_client_applies_a_rack_preset(http, caplog):
    rack = {"scope": "A1", "effects": [{"id": "fx_9", "effect": "parametric_eq"}], "revision": 12}
    url = "/api/audio/be_proj_1/rack/apply_preset"
    fake = http({("POST", url): (200, rack)})
    assert buzzedit_client.BuzzEditClient().apply_rack_preset("be_proj_1", "A1", "Podcast") == rack
    assert fake.calls == [("POST", url, {"scope": "A1", "name": "Podcast"})]

    http({("POST", url): (404, {"detail": "No rack preset 'Gone'"})})
    with caplog.at_level(logging.WARNING, logger="buzzcaf_ai.buzzedit_client"):
        assert buzzedit_client.BuzzEditClient().apply_rack_preset("be_proj_1", "A1", "Gone") is None
    assert "Could not apply the audio rack preset 'Gone'" in caplog.text
    assert "No rack preset 'Gone'" in caplog.text


def test_the_client_answers_none_when_buzzedit_is_not_running(caplog):
    with caplog.at_level(logging.WARNING, logger="buzzcaf_ai.buzzedit_client"):
        assert buzzedit_client.BuzzEditClient().list_rack_presets() is None
        assert buzzedit_client.BuzzEditClient().apply_rack_preset("be_proj_1", "A1", "Podcast") is None
    assert caplog.text.count("not reachable") == 2


# ------------------------------------------------------------ the render hook


def test_the_hook_puts_the_channels_preset_on_a1_and_records_it(monkeypatch, project):
    _channels(monkeypatch, {"Life3Baje": "Podcast"})
    calls = _fake_apply(monkeypatch)
    used = produce_api.apply_audio_rack_to_buzzedit(project, produce_api.BuzzEditClient(), "be_proj_1")
    assert used == PODCAST_RACK
    assert calls == [("be_proj_1", "A1", "Podcast")]
    assert Project.load(project.id).metadata["audio_rack_used"] == PODCAST_RACK
    assert produce_api._get_status(project.id)["audio_rack_used"] == PODCAST_RACK


def test_the_hook_records_nothing_without_a_preset_or_buzzedit(monkeypatch, project):
    project.metadata["audio_rack_used"] = {"audio_rack_preset": "Old", "scope": "A1", "effects": []}
    project.save()
    calls = _fake_apply(monkeypatch)
    _channels(monkeypatch, {"Raat3Baje": "Podcast"})                       # another channel's
    assert produce_api.apply_audio_rack_to_buzzedit(project, produce_api.BuzzEditClient(), "be_proj_1") is None
    assert calls == []
    assert "audio_rack_used" not in Project.load(project.id).metadata     # not last run's
    assert produce_api._get_status(project.id)["audio_rack_used"] is None

    _channels(monkeypatch, {"Life3Baje": "Podcast"})
    assert produce_api.apply_audio_rack_to_buzzedit(project, produce_api.BuzzEditClient(), None) is None
    assert calls == []                                                     # no BuzzEdit edit yet

    monkeypatch.setattr(produce_api.BuzzEditClient, "apply_rack_preset", lambda self, pid, scope, name: None)
    assert produce_api.apply_audio_rack_to_buzzedit(project, produce_api.BuzzEditClient(), "be_proj_1") is None
    assert "audio_rack_used" not in Project.load(project.id).metadata     # BuzzEdit did not take it


def _kept_words(words):
    out, t = [], 0.0
    for w in words:
        out.append({"word": w, "start": t, "end": t + 0.4})
        t += 0.5
    return out


def test_a_production_carries_the_channels_rack_into_the_render(monkeypatch, project):
    """Straight through `_plan_and_render` (no review gate), BuzzEdit faked:
    the preset lands on A1 before the render is enqueued, and the finished
    run reports it."""
    project.metadata["video_settings"] = {"review_mode": "none"}
    project.save()
    _channels(monkeypatch, {"Life3Baje": "Podcast"})
    order = []
    _fake_apply(monkeypatch, order)
    words = ["Hello", "world", "welcome", "to", "the", "show"]
    monkeypatch.setattr(produce_api.BuzzEditClient, "get_kept_words", lambda self, pid: _kept_words(words))
    monkeypatch.setattr(produce_api, "plan_visual_windows", lambda *a, **k: {
        "beats": [{"kind": "broll_image", "anchor": "welcome to the show", "start": 1.0, "end": 2.0,
                   "window_index": 0, "prompt": "a lonely street", "image_prompt": "a lonely street"}],
        "windows": 1, "ok": 1, "failed": []})
    monkeypatch.setattr(produce_api.BuzzEditClient, "set_script", lambda self, pid, text: {"ok": True})
    monkeypatch.setattr(produce_api.BuzzEditClient, "enqueue_presentation",
                        lambda self, pid, settings, start_at="": order.append("enqueue") or {"job": {"id": "job_1"}})
    monkeypatch.setattr(produce_api.BuzzEditClient, "get_jobs",
                        lambda self: {"jobs": [{"id": "job_1", "status": "completed", "progress": 1.0}]})
    monkeypatch.setattr(produce_api.BuzzEditClient, "get_report", lambda self, pid: {"output_path": "/out/video.mp4"})
    monkeypatch.setattr(produce_api, "_free_gpu_for_render", lambda project_id: None)

    produce_api._plan_and_render(project.id, "record_first", None, False)

    status = produce_api._get_status(project.id)
    assert status["state"] == "ready"
    assert order == [("apply", "A1", "Podcast"), "enqueue"]
    assert status["audio_rack_used"] == PODCAST_RACK
    assert Project.load(project.id).metadata["audio_rack_used"] == PODCAST_RACK


# -------------------------------------------------- Projects page and Dexter


def test_the_projects_page_gets_the_presets_and_the_channel_table(client, monkeypatch):
    _channels(monkeypatch, {"Life3Baje": "Podcast"})
    presets = {"Podcast": {"effects": [], "created": "2026-10-09T10:00:00", "note": ""}}
    monkeypatch.setattr(produce_api.BuzzEditClient, "list_rack_presets", lambda self: presets)
    assert client.get("/api/produce/audio_rack_presets").json() == {
        "available": True, "presets": presets, "channels": {"Life3Baje": "Podcast"}}

    monkeypatch.setattr(produce_api.BuzzEditClient, "list_rack_presets", lambda self: None)
    body = client.get("/api/produce/audio_rack_presets").json()
    assert body["available"] is False and body["presets"] == {}


def test_dexter_reads_and_applies_audio_racks(monkeypatch, project):
    _channels(monkeypatch, {"Life3Baje": "Podcast"})
    monkeypatch.setattr(produce_api.BuzzEditClient, "list_rack_presets",
                        lambda self: {"Podcast": {"effects": [], "created": "", "note": ""}})
    monkeypatch.setattr(produce_api.BuzzEditClient, "get_project", lambda self, pid: {
        "timeline": {"audio_racks": {"A1": [{"id": "fx_1", "effect": "parametric_eq"}], "MASTER": []}}})
    calls = _fake_apply(monkeypatch)

    presets = dexter_registry.invoke("audio_rack_presets", {})
    assert presets["status"] == "success" and presets["kind"] == "read"
    assert list(presets["result"]["presets"]) == ["Podcast"]

    rack = dexter_registry.invoke("audio_rack_of_project", {"project": project.id})
    assert rack["status"] == "success" and rack["kind"] == "read"
    assert rack["result"]["racks"]["A1"] == [{"id": "fx_1", "effect": "parametric_eq"}]
    assert rack["result"]["channel_preset"] == "Podcast"
    assert rack["result"]["buzzedit_project_id"] == "be_proj_1"

    applied = dexter_registry.invoke("apply_audio_rack_preset", {"project": project.id, "name": "Podcast"})
    assert applied["status"] == "success" and applied["kind"] == "write"
    assert calls == [("be_proj_1", "A1", "Podcast")]
    assert applied["result"]["audio_rack_preset"] == "Podcast" and applied["result"]["revision"] == 7

    assert dexter_registry.invoke("apply_audio_rack_preset", {"project": project.id})["code"] == 422
    assert dexter_registry.invoke("audio_rack_of_project", {})["code"] == 422
    assert dexter_registry.invoke("audio_rack_of_project", {"project": "no_such_project"})["code"] == 404
    monkeypatch.setattr(produce_api.BuzzEditClient, "apply_rack_preset", lambda self, pid, scope, name: None)
    assert dexter_registry.invoke("apply_audio_rack_preset",
                                  {"project": project.id, "name": "Gone"})["code"] == 502

    bare = Project.load(project.id)
    bare.metadata.pop("buzzedit_project_id")
    bare.save()
    assert dexter_registry.invoke("audio_rack_of_project", {"project": project.id})["result"]["racks"] is None
    assert dexter_registry.invoke("apply_audio_rack_preset",
                                  {"project": project.id, "name": "Podcast"})["code"] == 409


def test_the_audio_actions_are_reads_plus_one_safe_write_and_no_delete():
    audio = {c["name"]: c["kind"] for c in dexter_registry.CAPABILITIES if c["domain"] == "audio"}
    assert audio == {"audio_rack_presets": "read", "audio_rack_of_project": "read",
                     "apply_audio_rack_preset": "write"}
    unattended = {a["name"] for a in strategist_runner.allowed_actions()}
    assert set(audio) <= unattended
