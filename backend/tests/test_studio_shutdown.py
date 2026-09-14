"""
`POST /api/studio/shutdown` and the Sentinel gate in front of LM Studio
(roadmap v10, S1).

Nothing here may actually end the interpreter: the route's exit is factored
into `studio_api._shutdown_process`, and every test replaces it.
"""

import pytest
from fastapi.testclient import TestClient

from app.api import studio_api
from app.main import app
from integrations import llm as llm_module
from integrations.llm import LLMService, estimate_model_mib


@pytest.fixture
def local_client(monkeypatch):
    """A client whose requests look like they came from this machine, with the
    real exit replaced by a recorder."""
    calls = []
    monkeypatch.setattr(studio_api, "_shutdown_process", lambda: calls.append("exit"))
    monkeypatch.setattr(studio_api, "SHUTDOWN_GRACE_SECONDS", 0)
    client = TestClient(app, client=("127.0.0.1", 51234))
    return client, calls


# ───────────────────────────────── the route ─────────────────────────────────


def test_shutdown_answers_ok_and_then_exits(local_client):
    client, calls = local_client
    response = client.post("/api/studio/shutdown")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "shutting down" in body["message"].lower()
    # The exit is a background task, so the caller has its answer first.
    assert calls == ["exit"]


def test_shutdown_from_ipv6_loopback_is_accepted(monkeypatch):
    calls = []
    monkeypatch.setattr(studio_api, "_shutdown_process", lambda: calls.append("exit"))
    monkeypatch.setattr(studio_api, "SHUTDOWN_GRACE_SECONDS", 0)
    client = TestClient(app, client=("::1", 51234))
    assert client.post("/api/studio/shutdown").json()["ok"] is True
    assert calls == ["exit"]


def test_shutdown_from_off_machine_is_refused_and_nothing_exits(monkeypatch):
    calls = []
    monkeypatch.setattr(studio_api, "_shutdown_process", lambda: calls.append("exit"))
    monkeypatch.setattr(studio_api, "SHUTDOWN_GRACE_SECONDS", 0)
    client = TestClient(app, client=("192.168.1.50", 51234))
    response = client.post("/api/studio/shutdown")
    assert response.status_code == 403
    assert response.json()["ok"] is False
    assert calls == []


def test_a_hostname_is_not_a_loopback_address():
    # TestClient's own default peer is the hostname "testclient"; a name that
    # does not parse as an address must never pass the check.
    assert studio_api._is_loopback("testclient") is False
    assert studio_api._is_loopback("") is False
    assert studio_api._is_loopback("localhost") is False
    assert studio_api._is_loopback("127.0.0.1") is True
    assert studio_api._is_loopback("127.5.5.5") is True
    assert studio_api._is_loopback("10.0.0.1") is False


def test_the_deferred_task_calls_the_current_exit_function(monkeypatch):
    # `_deferred_shutdown` must look the function up on the module, not capture
    # it, or patching it in a test (or at runtime) would have no effect.
    calls = []
    monkeypatch.setattr(studio_api, "SHUTDOWN_GRACE_SECONDS", 0)
    monkeypatch.setattr(studio_api, "_shutdown_process", lambda: calls.append("exit"))
    studio_api._deferred_shutdown()
    assert calls == ["exit"]


# ─────────────────────────── the Sentinel gate on LM Studio ───────────────────────────


class _FakeSentinel:
    """Stands in for `integrations.sentinel_client.client()`."""

    def __init__(self, granted, details=None):
        self.granted = granted
        self.details = details or {}
        self.asked = []

    def query(self, mib, ram_mib=None):
        self.asked.append((mib, ram_mib))
        return self.granted, self.details


@pytest.fixture
def sentinel(monkeypatch):
    """Install a fake Sentinel and hand it back so a test can set the answer."""
    holder = {}

    def install(granted, details=None):
        fake = _FakeSentinel(granted, details)
        monkeypatch.setattr(
            "integrations.sentinel_client.client", lambda: fake, raising=True
        )
        holder["fake"] = fake
        return fake

    return install


def test_a_refused_query_skips_lm_studio_and_falls_through(monkeypatch, sentinel):
    fake = sentinel(
        False,
        {"reason": "not enough free VRAM", "free_mib": 900,
         "blockers": [{"process": "VrDeep", "vram_mib": 10240}]},
    )
    service = LLMService()
    service.config = {
        "selected_provider": "lm_studio",
        "lm_studio_model": "meta-llama-3-8b-instruct",
        "llamacpp_model": "local-model",
    }
    monkeypatch.setattr(LLMService, "reload_config", lambda self: None)

    tried = []

    def fake_local(self, base_url, model, system_prompt, user_prompt, temperature=0.7):
        tried.append(base_url)
        return "llamacpp answered"

    monkeypatch.setattr(LLMService, "_call_local", fake_local)

    out = service.generate_text("system", "user")
    assert out == "llamacpp answered"
    # LM Studio was asked about and skipped; llama.cpp was reached instead.
    assert fake.asked == [(6144, None)]
    assert all("1234" not in url for url in tried), tried
    assert any("8089" in url for url in tried), tried


def test_a_granted_query_lets_lm_studio_through(monkeypatch, sentinel):
    fake = sentinel(True, {"granted": True, "free_mib": 14000})
    service = LLMService()
    service.config = {
        "selected_provider": "lm_studio",
        "lm_studio_model": "meta-llama-3-8b-instruct",
    }
    monkeypatch.setattr(LLMService, "reload_config", lambda self: None)
    tried = []
    monkeypatch.setattr(
        LLMService,
        "_call_local",
        lambda self, base_url, model, s, u, temperature=0.7: (tried.append(base_url), "ok")[1],
    )
    assert service.generate_text("system", "user") == "ok"
    assert "1234" in tried[0]
    assert fake.asked == [(6144, None)]


def test_the_chat_path_is_gated_too(monkeypatch, sentinel):
    fake = sentinel(False, {"reason": "VRAM is Red"})
    service = LLMService()
    service.config = {"selected_provider": "lm_studio", "lm_studio_model": "some-13b-model"}
    monkeypatch.setattr(LLMService, "reload_config", lambda self: None)
    tried = []
    monkeypatch.setattr(
        LLMService,
        "_chat_openai_compat",
        lambda self, url, headers, model, s, m, j, t=0.7, timeout=90: (tried.append(url), "ok")[1],
    )
    service.generate_chat("system", [{"role": "user", "content": "hi"}])
    assert all("1234" not in url for url in tried), tried
    # 13B, so the number on the wire is not the 8B default.
    assert fake.asked == [(9344, None)]


def test_llamacpp_is_not_gated(monkeypatch, sentinel):
    # buzzcode's engine reserves for itself before it starts; asking again here
    # would book the same 12 GB twice.
    fake = sentinel(False, {"reason": "should never be consulted"})
    service = LLMService()
    service.config = {"selected_provider": "llamacpp", "llamacpp_model": "local-model"}
    monkeypatch.setattr(LLMService, "reload_config", lambda self: None)
    monkeypatch.setattr(
        LLMService, "_call_local", lambda self, base_url, model, s, u, temperature=0.7: "ok"
    )
    assert service.generate_text("system", "user") == "ok"
    assert fake.asked == []


def test_an_unreachable_sentinel_never_blocks_lm_studio(monkeypatch):
    def explode():
        raise RuntimeError("pipe is gone")

    monkeypatch.setattr("integrations.sentinel_client.client", explode, raising=True)
    service = LLMService()
    service.config = {"selected_provider": "lm_studio", "lm_studio_model": "x-8b"}
    monkeypatch.setattr(LLMService, "reload_config", lambda self: None)
    assert service._sentinel_allows("lm_studio") is True


# ───────────────────────────── the size estimate ─────────────────────────────


@pytest.mark.parametrize(
    "name,expected",
    [
        ("meta-llama-3-8b-instruct", 6144),
        ("qwen2.5-7b-instruct", 5504),
        ("gpt-oss-20b", 13824),
        ("local-model", llm_module.LM_STUDIO_DEFAULT_MIB),
        ("", llm_module.LM_STUDIO_DEFAULT_MIB),
        (None, llm_module.LM_STUDIO_DEFAULT_MIB),
        # A number that is plainly not a parameter count falls back rather than
        # asking Sentinel for a terabyte.
        ("something-99999b", llm_module.LM_STUDIO_DEFAULT_MIB),
    ],
)
def test_model_size_estimates(name, expected):
    assert estimate_model_mib(name) == expected
