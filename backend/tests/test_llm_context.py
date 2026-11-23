from integrations import llm
from runtime.context_budget import fit_messages, estimate_tokens


def test_overflow_tokens_parse():
    assert llm._overflow_tokens(Exception("request (21025 tokens) exceeds the available context size")) == 21025
    assert llm._overflow_tokens(Exception("connection refused")) is None


def test_grow_to_fit(monkeypatch):
    cfg = {"lm_studio_context_length": 32768, "lm_studio_max_context_length": 131072,
           "local_max_output_tokens": 2048}
    monkeypatch.setattr(llm, "load_config", lambda: dict(cfg))
    monkeypatch.setattr(llm, "lm_studio_loaded_context", lambda model, *a, **k: 32768)
    calls = []
    monkeypatch.setattr(llm, "reload_lm_studio_model", lambda m, c: calls.append(c) or True)
    svc = llm.LLMService.__new__(llm.LLMService)
    svc._grow_lm_studio_context("m", need=40000)
    assert calls == [49152]
    svc._grow_lm_studio_context("m", need=200000)
    assert max(calls) <= 131072


def test_fit_messages_memory_first():
    system = "persona\n### Persistent Agent Memory Context\n" + "m" * 20000
    msgs = [{"role": "user", "content": "hello"}, {"role": "user", "content": "last question"}]
    budget = estimate_tokens("persona", msgs) + 10
    s, m = fit_messages(system, msgs, budget)
    assert "Persistent Agent Memory" not in s
    assert m[-1]["content"] == "last question"
    assert estimate_tokens(s, m) <= budget
