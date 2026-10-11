"""
`sfx_library_dirs` settings -> BuzzEdit's SFX library: `BuzzEditClient`'s push
(with its settings fallback for an older BuzzEdit without the dedicated
route), the best-effort sync before a production, and the
`/api/produce/sfx/library` proxy routes.
"""

import pytest
from fastapi.testclient import TestClient

from app.api import produce_api
from app.main import SettingsSchema, app
from integrations.buzzedit_client import BuzzEditClient


class _FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or str(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")


@pytest.fixture
def client():
    return TestClient(app)


# ------------------------------------------------------- BuzzEditClient


def test_set_sfx_library_falls_back_to_set_app_settings_when_the_route_is_missing(monkeypatch):
    client_obj = BuzzEditClient()
    monkeypatch.setattr(client_obj, "_send", lambda method, path, timeout, **kw: _FakeResponse(404, text="missing"))
    settings_calls = []
    monkeypatch.setattr(client_obj, "set_app_settings",
                        lambda updates: settings_calls.append(updates) or {"ok": True})

    result = client_obj.set_sfx_library(["C:/sfx/one", "C:/sfx/two"])

    assert result == {"dirs": ["C:/sfx/one", "C:/sfx/two"], "fallback": True}
    assert settings_calls == [{"sfx_library_dirs": ["C:/sfx/one", "C:/sfx/two"]}]


def test_set_sfx_library_uses_the_dedicated_route_when_it_answers(monkeypatch):
    client_obj = BuzzEditClient()
    monkeypatch.setattr(client_obj, "_send",
                        lambda method, path, timeout, **kw: _FakeResponse(200, {"dirs": ["a"], "count": 3}))

    result = client_obj.set_sfx_library(["a"])

    assert result == {"dirs": ["a"], "count": 3}


def test_set_sfx_library_returns_none_when_the_route_and_the_fallback_both_fail(monkeypatch):
    client_obj = BuzzEditClient()
    monkeypatch.setattr(client_obj, "_send", lambda method, path, timeout, **kw: _FakeResponse(500, text="down"))

    def _boom(updates):
        raise RuntimeError("BuzzEdit is down")

    monkeypatch.setattr(client_obj, "set_app_settings", _boom)

    assert client_obj.set_sfx_library(["a"]) is None


# -------------------------------------------------- sync before production


def test_sync_sfx_library_to_buzzedit_pushes_the_saved_dirs(monkeypatch):
    monkeypatch.setattr(produce_api, "load_llm_config", lambda: {"sfx_library_dirs": ["C:/sfx/one", "  "]})
    pushed = []

    class _FakeClient:
        def set_sfx_library(self, dirs):
            pushed.append(dirs)
            return {"dirs": dirs}

    result = produce_api.sync_sfx_library_to_buzzedit(_FakeClient())

    assert pushed == [["C:/sfx/one"]]
    assert result == {"dirs": ["C:/sfx/one"]}


def test_sync_sfx_library_to_buzzedit_is_a_no_op_with_nothing_saved(monkeypatch):
    monkeypatch.setattr(produce_api, "load_llm_config", lambda: {})

    class _FakeClient:
        def set_sfx_library(self, dirs):
            raise AssertionError("must not be called with no saved dirs")

    assert produce_api.sync_sfx_library_to_buzzedit(_FakeClient()) is None


# -------------------------------------------------------------- settings


def test_settings_schema_accepts_sfx_library_dirs():
    settings = SettingsSchema(sfx_library_dirs=["C:/sfx/one", "C:/sfx/two"])
    assert settings.sfx_library_dirs == ["C:/sfx/one", "C:/sfx/two"]


# ------------------------------------------------------------------ routes


def test_get_sfx_library_route_reports_saved_dirs_and_buzzedit_summary(client, monkeypatch):
    monkeypatch.setattr(produce_api, "load_llm_config", lambda: {"sfx_library_dirs": ["C:/sfx/one"]})
    monkeypatch.setattr(BuzzEditClient, "get_sfx_library",
                        lambda self: {"dirs": ["C:/sfx/one"], "default": ["C:/sfx/one"], "count": 5})

    resp = client.get("/api/produce/sfx/library")

    assert resp.status_code == 200
    body = resp.json()
    assert body["dirs"] == ["C:/sfx/one"]
    assert body["default"] == ["C:/sfx/one"]
    assert body["buzzedit"]["count"] == 5


def test_get_sfx_library_route_when_buzzedit_is_offline(client, monkeypatch):
    monkeypatch.setattr(produce_api, "load_llm_config", lambda: {})
    monkeypatch.setattr(BuzzEditClient, "get_sfx_library", lambda self: None)

    resp = client.get("/api/produce/sfx/library")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"dirs": [], "default": [], "buzzedit": None}


def test_put_sfx_library_route_saves_and_pushes(client, monkeypatch):
    saved = {}
    monkeypatch.setattr(produce_api, "load_llm_config", lambda: {})
    monkeypatch.setattr(produce_api, "save_llm_config", lambda cfg: saved.update(cfg))
    monkeypatch.setattr(BuzzEditClient, "_put",
                        lambda self, path, json_body=None, timeout=None: _FakeResponse(
                            200, {"dirs": json_body["dirs"], "count": 2}))

    resp = client.put("/api/produce/sfx/library", json={"dirs": ["C:/sfx/one", " "]})

    assert resp.status_code == 200
    body = resp.json()
    assert body["dirs"] == ["C:/sfx/one"]
    assert body["buzzedit"]["count"] == 2
    assert saved["sfx_library_dirs"] == ["C:/sfx/one"]


def test_put_sfx_library_route_surfaces_a_422_from_buzzedit(client, monkeypatch):
    monkeypatch.setattr(produce_api, "load_llm_config", lambda: {})
    monkeypatch.setattr(produce_api, "save_llm_config", lambda cfg: None)
    monkeypatch.setattr(BuzzEditClient, "_put",
                        lambda self, path, json_body=None, timeout=None: _FakeResponse(
                            422, {"detail": "no such folder: C:/nope"}))

    resp = client.put("/api/produce/sfx/library", json={"dirs": ["C:/nope"]})

    assert resp.status_code == 422
    assert "C:/nope" in resp.json()["detail"]


def test_put_sfx_library_route_tolerates_buzzedit_offline(client, monkeypatch):
    monkeypatch.setattr(produce_api, "load_llm_config", lambda: {})
    monkeypatch.setattr(produce_api, "save_llm_config", lambda cfg: None)

    def _boom(self, path, json_body=None, timeout=None):
        raise produce_api.BuzzEditUnavailable("not running")

    monkeypatch.setattr(BuzzEditClient, "_put", _boom)

    resp = client.put("/api/produce/sfx/library", json={"dirs": ["C:/sfx/one"]})

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"dirs": ["C:/sfx/one"], "default": [], "buzzedit": None}


def test_refresh_sfx_library_route_502_when_buzzedit_does_not_answer(client, monkeypatch):
    monkeypatch.setattr(BuzzEditClient, "refresh_sfx_library", lambda self: None)

    resp = client.post("/api/produce/sfx/library/refresh")

    assert resp.status_code == 502


def test_generate_sfx_route_offline_is_502(client, monkeypatch):
    def _offline(self, text, kind="accent", seconds=None):
        raise produce_api.BuzzEditUnavailable("not running")

    monkeypatch.setattr(BuzzEditClient, "generate_sfx", _offline)

    resp = client.post("/api/produce/sfx/generate", json={"text": "a door creaks"})

    assert resp.status_code == 502


def test_generate_sfx_route_comfyui_offline_is_503(client, monkeypatch):
    def _busy(self, text, kind="accent", seconds=None):
        raise RuntimeError("HTTP 503: ComfyUI is offline")

    monkeypatch.setattr(BuzzEditClient, "generate_sfx", _busy)

    resp = client.post("/api/produce/sfx/generate", json={"text": "a door creaks"})

    assert resp.status_code == 503


def test_get_sfx_job_route_404_for_an_unknown_job(client, monkeypatch):
    monkeypatch.setattr(BuzzEditClient, "_get", lambda self, path, timeout=None: _FakeResponse(404))

    resp = client.get("/api/produce/sfx/jobs/nope")

    assert resp.status_code == 404
