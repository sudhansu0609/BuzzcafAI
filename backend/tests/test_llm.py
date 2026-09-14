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
    service = LLMService()
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
