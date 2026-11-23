"""Model routing (2026-10-26): per-job routes, Day/Night profiles, the usage
record and the nightly forecast's arithmetic."""
from unittest.mock import MagicMock, patch

from integrations import llm, llm_usage
from integrations.llm import DEFAULT_TIERS, LLMService, job_for_asset, llm_job, route_profile_as


def _service(**overrides) -> LLMService:
    service = LLMService()
    service.reload_config = MagicMock()
    config = {
        "gemini_api_key": "", "openai_api_key": "", "local_only": False,
        "lm_studio_url": "http://localhost:1234/v1", "lm_studio_model": "gemma",
        "claude_url": "http://127.0.0.1:8787/v1", "claude_api_key": "sk-test", "claude_model": "haiku",
        "tiers": {k: dict(v) for k, v in DEFAULT_TIERS.items()}, "selected_provider": "lm_studio",
        "job_routes": {"script": {"provider": "claude", "model": "opus", "fallback": "lm_studio"}},
        "job_routes_night": {"script": {"provider": "lm_studio", "model": "", "fallback": "claude"}},
    }
    config.update(overrides)
    service.config = config
    return service


def test_steps_map_to_jobs():
    assert job_for_asset("research") == "research"
    assert job_for_asset("script") == "script"
    assert job_for_asset("shorts_set") == "shorts"
    assert job_for_asset("seo_package") == "seo"
    assert job_for_asset("visual_plan") == "planning"
    assert job_for_asset("unknown_asset") is None


def test_day_route_puts_claude_first_with_its_model():
    svc = _service()
    with route_profile_as("day"), llm_job("script"):
        order = svc._provider_order("premium")
        assert order[:2] == ["claude", "lm_studio"]
        assert svc._model_for("claude", "premium") == "opus"


def test_night_route_puts_gemma_first_and_claude_fallback_is_sonnet():
    svc = _service()
    with route_profile_as("night"), llm_job("script"):
        order = svc._provider_order("premium")
        assert order[0] == "lm_studio"
        assert order.index("claude") == 1
        assert svc._model_for("claude", "premium") == "sonnet"


def test_no_job_keeps_the_persona_tier():
    svc = _service(tiers={"strong": {"provider": "claude", "model": "haiku"}})
    assert svc._provider_order("strong")[0] == "claude"


def test_night_falls_back_to_the_day_route_for_a_job_it_does_not_name():
    cfg = {"job_routes": {"seo": {"provider": "claude", "model": "sonnet"}}, "job_routes_night": {"script": {}}}
    assert llm.job_routes(cfg, profile="night")["seo"]["provider"] == "claude"


def test_route_profile_follows_the_clock_and_the_env(monkeypatch):
    cfg = {"job_routes_night": {"script": {"provider": "lm_studio"}}, "night_hours": {"start": "22:00", "end": "09:00"}}

    class _Clock:
        @staticmethod
        def now():
            from datetime import datetime
            return datetime(2026, 10, 27, 3, 0)

    monkeypatch.delenv("BUZZCAF_ROUTE_PROFILE", raising=False)
    monkeypatch.setattr(llm, "datetime", _Clock)
    assert llm.route_profile(cfg) == "night"
    monkeypatch.setenv("BUZZCAF_ROUTE_PROFILE", "day")
    assert llm.route_profile(cfg) == "day"


def test_every_call_is_recorded_with_its_job_and_tokens():
    svc = _service(job_routes={}, job_routes_night={})
    ok = MagicMock(status_code=200)
    ok.json.return_value = {"choices": [{"message": {"content": "hello"}}],
                            "usage": {"prompt_tokens": 1200, "completion_tokens": 80}}
    with patch("integrations.llm.requests.post", return_value=ok), \
            patch.object(LLMService, "_sentinel_allows", return_value=True), \
            patch.object(LLMService, "_resolve_lm_studio_model", side_effect=lambda m: m), \
            patch.object(LLMService, "_lm_studio_ready"), \
            patch.object(LLMService, "_lm_studio_fit", side_effect=lambda m, s, ms: (s, ms)), \
            llm_job("seo", "wf/SEO/p1"):
        assert svc.generate_text("System", user_prompt="Write tags") == "hello"
    rows = llm_usage.calls(days=1)
    assert rows[-1]["job"] == "seo" and rows[-1]["step"] == "wf/SEO/p1"
    assert rows[-1]["in"] == 1200 and rows[-1]["out"] == 80 and rows[-1]["estimated"] is False
    assert rows[-1]["provider"] == "lm_studio" and rows[-1]["ok"] is True


def test_upper_quartile_and_worst_case():
    from app.services import run_forecast
    assert run_forecast._p75([3, 4, 5, 30]) == 5
    assert run_forecast._p75([10]) == 10
