"""
Model tiers, the local llama.cpp provider and per-persona temperature
(roadmap v9, F1/F2).

What these protect: cheap work is offered to the fast tier's provider first, a
tier that is down still falls through the normal order, the tier mapping
round-trips through /api/settings, and a persona's declared temperature reaches
the provider payload rather than a hard-coded 0.7.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from core.agent import AgentFactory, agent_registry
from integrations.llm import DEFAULT_TIERS, LLMService


def _service(**overrides) -> LLMService:
    """An LLMService with a fixed config, so no test reads the real one."""
    purpose = overrides.pop("purpose", "agents")
    service = LLMService(purpose=purpose)
    service.reload_config = MagicMock()
    config = {
        "gemini_api_key": "",
        "openai_api_key": "",
        "lm_studio_url": "http://localhost:1234/v1",
        "lm_studio_model": "lmstudio-model",
        "llamacpp_url": "http://127.0.0.1:8089/v1",
        "llamacpp_model": "gemma-27b",
        "tiers": {k: dict(v) for k, v in DEFAULT_TIERS.items()},
        "selected_provider": "lm_studio",
    }
    config.update(overrides)
    service.config = config
    return service


def _ok(content="hello"):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"choices": [{"message": {"content": content}}]}
    return response


def test_fast_tier_goes_to_llamacpp_first():
    service = _service()
    with patch("integrations.llm.requests.post", return_value=_ok("from llama.cpp")) as post:
        assert service.generate_text("System", "Tag this", tier="fast") == "from llama.cpp"
    url, = post.call_args[0]
    assert "127.0.0.1:8089" in url
    assert post.call_args[1]["json"]["model"] == "gemma-27b"


def test_strong_tier_uses_the_selected_provider():
    service = _service()
    with patch("integrations.llm.requests.post", return_value=_ok("from lm studio")) as post:
        assert service.generate_text("System", "Write this", tier="strong") == "from lm studio"
    assert "localhost:1234" in post.call_args[0][0]


def test_fast_tier_falls_back_when_llamacpp_is_down():
    service = _service()
    calls = []

    def flaky(url, **kwargs):
        calls.append(url)
        if "8089" in url:
            raise ConnectionError("llama.cpp is not running")
        return _ok("from lm studio")

    with patch("integrations.llm.requests.post", side_effect=flaky):
        assert service.generate_text("System", "Tag this", tier="fast") == "from lm studio"
    assert "8089" in calls[0] and "1234" in calls[1]


def test_provider_order_puts_the_tier_first_then_the_selection():
    service = _service(selected_provider="openai")
    assert service._provider_order("fast")[:2] == ["llamacpp", "openai"]
    assert service._provider_order("strong")[0] == "openai"
    assert service._provider_order(None)[0] == "openai"


def test_tier_settings_round_trip_through_the_api(tmp_path, monkeypatch):
    # Settings are written to disk, so point the writer at a throwaway file:
    # the real backend/config/config.json must survive the suite untouched.
    import integrations.llm as llm_module

    monkeypatch.setattr(llm_module, "CONFIG_PATH", str(tmp_path / "config.json"))
    client = TestClient(app)
    res = client.post("/api/settings", json={
        "tiers": {"fast": {"provider": "llamacpp", "model": "gemma-27b"},
                  "strong": {"provider": "gemini", "model": "gemini-1.5-pro"}},
        "llamacpp_url": "http://127.0.0.1:8089/v1",
    })
    assert res.status_code == 200, res.text
    stored = client.get("/api/settings").json()
    assert stored["tiers"]["fast"] == {"provider": "llamacpp", "model": "gemma-27b"}
    assert stored["tiers"]["strong"] == {"provider": "gemini", "model": "gemini-1.5-pro"}
    assert stored["llamacpp_url"] == "http://127.0.0.1:8089/v1"


def test_the_seven_cheap_personas_are_on_the_fast_tier():
    fast = {name for name, a in agent_registry.agents.items() if a.model_tier == "fast"}
    assert fast == {
        "taggenerator", "titlegenerator", "descriptionwriter", "metadataoptimizer",
        "publishingchecklist", "taxonomymanager", "citationarchivist",
    }


@pytest.mark.parametrize("persona,expected", [("HorrorWriter", 0.9), ("FactChecker", 0.2)])
def test_persona_temperature_reaches_the_provider_payload(persona, expected):
    agent = AgentFactory.get_agent(persona, _service())
    assert agent.temperature == expected
    with patch("integrations.llm.requests.post", return_value=_ok("done")) as post:
        agent.execute("Write the opening beat.")
    assert post.call_args[1]["json"]["temperature"] == expected


def test_a_persona_with_no_temperature_uses_the_studio_default():
    agent = AgentFactory.get_agent("ScriptWriter", _service())
    assert agent.temperature == 0.7
    with patch("integrations.llm.requests.post", return_value=_ok("done")) as post:
        agent.execute("Write the opening beat.")
    assert post.call_args[1]["json"]["temperature"] == 0.7


# ------------------------------------------------- the Claude proxy provider
#
# "claude" is the claude-local-api proxy on loopback (integrations/llm.py,
# CLAUDE_DEFAULT_URL). It answers through the user's Claude login, so Strict
# Local Mode allows it only when asked for by name -- never as a fallback.


def test_claude_is_never_an_implicit_fallback_under_strict_local():
    service = _service(local_only=True, claude_api_key="sk-local-x")
    assert "claude" not in service._provider_order("strong")


def test_claude_is_allowed_under_strict_local_when_named_by_a_tier():
    service = _service(local_only=True, claude_api_key="sk-local-x")
    service.config["tiers"]["strong"] = {"provider": "claude", "model": ""}
    assert service._provider_order("strong")[0] == "claude"
    # ...but only for that tier: nothing else gets it.
    assert "claude" not in service._provider_order("fast")


def test_forced_provider_goes_first_and_the_normal_order_still_follows():
    service = _service(local_only=True, claude_api_key="sk-local-x")
    service.forced_provider = "claude"
    order = service._provider_order("strong")
    assert order[0] == "claude"
    assert order[1:] == ["lm_studio", "llamacpp", "ollama"]


def test_generate_text_calls_the_claude_proxy_with_the_bearer_key_and_no_response_format():
    service = _service(local_only=False, claude_api_key="sk-local-x",
                       claude_url="http://127.0.0.1:8787/v1", claude_model="haiku",
                       selected_provider="claude")
    with patch("integrations.llm.requests.post", return_value=_ok("from claude")) as post:
        assert service.generate_text("System", "Plan this", require_json=True) == "from claude"
    url = post.call_args[0][0]
    kwargs = post.call_args[1]
    assert url == "http://127.0.0.1:8787/v1/chat/completions"
    assert kwargs["headers"]["Authorization"] == "Bearer sk-local-x"
    assert kwargs["json"]["model"] == "haiku"
    assert "response_format" not in kwargs["json"]
    assert service.last_response_simulated is False


def test_claude_falls_through_to_the_local_model_when_the_proxy_is_down():
    service = _service(local_only=True, claude_api_key="sk-local-x")
    service.forced_provider = "claude"
    calls = []

    def flaky(url, **kwargs):
        calls.append(url)
        if "8787" in url:
            raise ConnectionError("proxy is not running")
        return _ok("from lm studio")

    with patch("integrations.llm.requests.post", side_effect=flaky):
        assert service.generate_text("System", "Plan this") == "from lm studio"
    assert "8787" in calls[0] and "1234" in calls[1]


def test_claude_without_a_key_is_skipped_silently():
    service = _service(local_only=False, claude_api_key="", selected_provider="claude")
    with patch("integrations.llm.requests.post", return_value=_ok("from lm studio")) as post:
        assert service.generate_text("System", "Plan this") == "from lm studio"
    assert "8787" not in post.call_args_list[0][0][0]


def test_gpu_providers_go_last_while_a_render_owns_the_card(monkeypatch):
    from integrations import llm as llm_module
    monkeypatch.setattr(llm_module, "_gpu_owned_by_render", lambda: True)
    assert llm_module._defer_gpu_providers(["lm_studio", "claude", "llamacpp"]) == ["claude", "lm_studio", "llamacpp"]
    # Nothing but local providers allowed (Strict Local): the order is kept.
    assert llm_module._defer_gpu_providers(["lm_studio", "llamacpp"]) == ["lm_studio", "llamacpp"]
    monkeypatch.setattr(llm_module, "_gpu_owned_by_render", lambda: False)
    assert llm_module._defer_gpu_providers(["lm_studio", "claude"]) == ["lm_studio", "claude"]


def test_thinking_defaults_on_for_agents_and_off_for_production():
    agents, production = LLMService(), LLMService(purpose="production")
    chat = LLMService(purpose="director_chat")
    agents.config = production.config = chat.config = {}
    assert agents._local_reasoning_effort("lm_studio") is None  # model thinks as usual
    assert agents._local_timeout() == 600
    assert production._local_reasoning_effort("lm_studio") == "none"
    assert production._local_timeout() == 180
    assert production._local_reasoning_effort("ollama") is None
    assert chat._local_reasoning_effort("lm_studio") == "none"
    assert chat._local_timeout() == 180


def test_thinking_switches_follow_settings():
    agents, production = LLMService(), LLMService(purpose="production")
    chat = LLMService(purpose="chat")
    agents.config = production.config = chat.config = {
        "thinking_agents": False,
        "thinking_production": True,
        "thinking_chat": True,
    }
    assert agents._local_reasoning_effort("lm_studio") == "none"
    assert production._local_reasoning_effort("lm_studio") is None
    assert chat._local_reasoning_effort("lm_studio") is None


# --- LM Studio context length -------------------------------------------------

OVERFLOW = ('http://localhost:1234/v1/chat/completions returned code 400: {"error":"request (21025 tokens) '
            'exceeds the available context size (16128 tokens), try increasing it"}')


def _lm_studio_service(monkeypatch, loaded=True):
    from integrations import llm

    service = llm.LLMService()
    service.config = {"selected_provider": "lm_studio", "lm_studio_model": "google/gemma-4-12b", "local_only": True}
    monkeypatch.setattr(llm.LLMService, "reload_config", lambda self: None)
    monkeypatch.setattr(llm.LLMService, "_sentinel_allows", lambda self, provider, tier=None: True)
    monkeypatch.setattr(llm.LLMService, "_resolve_lm_studio_model", lambda self, model: model)
    monkeypatch.setattr(llm.LLMService, "_is_lm_studio_model_loaded", lambda self, model: loaded)
    monkeypatch.setattr(llm, "lm_studio_context_length", lambda: 32768)
    return llm, service


def test_a_prompt_too_long_for_a_small_lm_studio_context_reloads_the_model_and_retries(monkeypatch):
    llm, service = _lm_studio_service(monkeypatch)
    monkeypatch.setattr(llm, "lm_studio_loaded_context", lambda model, base_url="": 16128)
    reloads, calls = [], []
    monkeypatch.setattr(llm, "reload_lm_studio_model", lambda model, context: reloads.append((model, context)) or True)

    def fake_local(self, base_url, model, system_prompt, user_prompt, temperature=0.7, **kw):
        calls.append(model)
        if len(calls) == 1:
            raise Exception(OVERFLOW)
        return "the plan"

    monkeypatch.setattr(llm.LLMService, "_call_local", fake_local)
    assert service.generate_text("system", "a very long script") == "the plan"
    assert reloads == [("google/gemma-4-12b", 32768)] and len(calls) == 2
    assert service.last_response_simulated is False


def test_a_model_already_at_the_studios_context_is_not_reloaded(monkeypatch):
    llm, service = _lm_studio_service(monkeypatch)
    monkeypatch.setattr(llm, "lm_studio_loaded_context", lambda model, base_url="": 32768)
    reloads = []
    monkeypatch.setattr(llm, "reload_lm_studio_model", lambda model, context: reloads.append(model) or True)
    assert service._grow_lm_studio_context("google/gemma-4-12b", Exception(OVERFLOW)) is False
    # Some other failure (a timeout) never reloads anything either.
    monkeypatch.setattr(llm, "lm_studio_loaded_context", lambda model, base_url="": 16128)
    assert service._grow_lm_studio_context("google/gemma-4-12b", Exception("Read timed out")) is False
    assert reloads == []


def test_a_model_that_is_not_in_memory_is_loaded_by_the_studio_not_by_lm_studios_default(monkeypatch):
    llm, service = _lm_studio_service(monkeypatch, loaded=False)
    loads = []
    monkeypatch.setattr(llm, "ensure_local_model_loaded",
                        lambda provider="lm_studio", model_name=None: loads.append((provider, model_name)) or {})
    monkeypatch.setattr(llm.LLMService, "_call_local", lambda self, *a, **kw: "ok")
    assert service.generate_text("system", "hello") == "ok"
    assert loads == [("lm_studio", "google/gemma-4-12b")]


# --- JSON mode on local servers --------------------------------------------------------

def test_local_json_mode_is_asked_for_and_dropped_when_the_server_refuses_it():
    calls = []

    def call(json_mode):
        calls.append(json_mode)
        if json_mode:
            raise Exception("http://127.0.0.1:11434/v1/chat/completions returned code 400: response_format")
        return "{}"

    assert LLMService._with_local_json_mode(True, call) == "{}"
    assert calls == [True, False]


def test_local_json_mode_does_not_hide_a_real_failure():
    def call(json_mode):
        raise Exception("http://127.0.0.1:11434/v1/chat/completions returned code 500: boom")

    with pytest.raises(Exception, match="code 500"):
        LLMService._with_local_json_mode(True, call)


def test_local_json_mode_is_not_used_when_json_is_not_required():
    assert LLMService._with_local_json_mode(False, lambda json_mode: json_mode) is False


def test_call_local_sends_response_format_only_when_json_is_required():
    svc = LLMService.__new__(LLMService)
    seen = {}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "{\"ok\": true}"}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen.update(json)
        return _Resp()

    with patch("integrations.llm.requests.post", side_effect=fake_post):
        LLMService._call_local(svc, "http://x/v1", "m", "sys", "user", require_json=True)
        assert seen["response_format"] == {"type": "json_object"}
        seen.clear()
        LLMService._call_local(svc, "http://x/v1", "m", "sys", "user")
        assert "response_format" not in seen


def test_gemini_harness_routing_and_execution():
    from integrations.llm import LLMService
    service = _service(selected_provider="gemini", gemini_url="http://127.0.0.1:8001", gemini_model="flash")
    seen = {}

    class _HarnessResp:
        status_code = 200

        @staticmethod
        def json():
            return {
                "model": "gemini-3.8-flash",
                "output": {
                    "status": "SUCCESS",
                    "response": "Hello from Gemini local harness!"
                }
            }

    def fake_post(url, json=None, timeout=None):
        seen["url"] = url
        seen["payload"] = json
        return _HarnessResp()

    with patch("integrations.llm.requests.post", side_effect=fake_post):
        reply = service.generate_text("Be helpful", "Who are you?")
        assert reply == "Hello from Gemini local harness!"
        assert "127.0.0.1:8001/api/gemini" in seen["url"]
        assert seen["payload"]["model"] == "flash"
        assert "Who are you?" in seen["payload"]["input"]


def test_gemini_harness_allowed_in_local_only():
    from integrations.llm import LLMService, is_local_gemini
    cfg = {"gemini_url": "http://127.0.0.1:8001", "local_only": True}
    assert is_local_gemini(cfg) is True

    service = _service(selected_provider="gemini", gemini_url="http://127.0.0.1:8001", local_only=True)
    order = service._provider_order()
    assert "gemini" in order


def test_gemini_probe_endpoint(tmp_path, monkeypatch):
    import integrations.llm as llm_module
    monkeypatch.setattr(llm_module, "CONFIG_PATH", str(tmp_path / "config.json"))

    class _OpenApiResp:
        status_code = 200

        @staticmethod
        def json():
            return {"info": {"title": "Gemini Antigravity CLI Harness API"}}

    with patch("integrations.llm.requests.get", return_value=_OpenApiResp()):
        client = TestClient(app)
        res = client.get("/api/gemini/status")
        assert res.status_code == 200
        data = res.json()
        assert data["online"] is True
        assert data["is_local"] is True
        assert "Gemini harness online" in data["message"]
        assert data["thinking_level"] == "high"
        assert "max" in data["thinking_levels"]


def test_gemini_effort_level_controls_and_payload():
    from integrations.llm import LLMService

    seen_payloads = []

    class _HarnessResp:
        status_code = 200

        @staticmethod
        def json():
            return {
                "model": "gemini-3.8-flash",
                "output": {
                    "status": "SUCCESS",
                    "response": "Thought carefully."
                }
            }

    def fake_post(url, json=None, timeout=None):
        seen_payloads.append(json)
        return _HarnessResp()

    # 1. Configured thinking level in config
    service = _service(selected_provider="gemini", gemini_url="http://127.0.0.1:8001", gemini_thinking_level="medium")
    assert service.gemini_effort_level() == "medium"

    with patch("integrations.llm.requests.post", side_effect=fake_post):
        service.generate_text("System", "User prompt")
        assert seen_payloads[-1]["thinking_level"] == "medium"

        # 2. Dynamic override passed to call
        service.generate_text("System", "User prompt", effort="max")
        assert seen_payloads[-1]["thinking_level"] == "max"

        service.generate_chat("System", [{"role": "user", "content": "Chat prompt"}], effort="low")
        assert seen_payloads[-1]["thinking_level"] == "low"

    # 3. Purpose with thinking disabled scales back to low by default
    prod_service = _service(selected_provider="gemini", gemini_url="http://127.0.0.1:8001", purpose="production", thinking_production=False)
    assert prod_service.gemini_effort_level() == "low"
    # But explicit override still works even in production:
    assert prod_service.gemini_effort_level(override="high") == "high"


def test_gemini_effort_level_settings_roundtrip():
    client = TestClient(app)
    res = client.post("/api/settings", json={"gemini_thinking_level": "max"})
    assert res.status_code == 200
    cfg = client.get("/api/settings").json()
    assert cfg["gemini_thinking_level"] == "max"



def test_writing_jobs_never_fall_back_to_claude_unless_routed_to_it():
    from integrations.llm import llm_job
    service = _service(local_only=False, claude_api_key="sk-local-x")
    service.config["job_routes"] = {"script": {"provider": "lm_studio", "fallback": "claude"}}
    with llm_job("script"):
        assert "claude" not in service._provider_order("strong")
    service.config["job_routes"] = {"script": {"provider": "claude"}}
    with llm_job("script"):
        assert service._provider_order("strong")[0] == "claude"
