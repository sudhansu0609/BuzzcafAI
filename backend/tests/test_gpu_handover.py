"""`_free_gpu_for_render` -- clearing LM Studio, llama.cpp and Ollama off the
card before ComfyUI renders. Every server and process here is faked."""
from types import SimpleNamespace

import pytest

from app.api import produce_api

# Captured at import, before conftest swaps them for no-ops.
_unload_lm_studio = produce_api._unload_lm_studio
_stop_llamacpp = produce_api._stop_llamacpp
_unload_ollama = produce_api._unload_ollama


@pytest.fixture
def ran(monkeypatch):
    calls = []
    monkeypatch.setattr(produce_api.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd) or SimpleNamespace(stdout="ok", stderr=""))
    return calls


def test_free_gpu_runs_every_step_even_when_one_fails(monkeypatch):
    seen = []

    def boom(project_id, cfg):
        seen.append("lms")
        raise RuntimeError("lms hung")

    monkeypatch.setattr(produce_api, "_unload_lm_studio", boom)
    monkeypatch.setattr(produce_api, "_stop_llamacpp", lambda p, c: seen.append("llamacpp"))
    monkeypatch.setattr(produce_api, "_unload_ollama", lambda p, c: seen.append("ollama"))
    monkeypatch.setattr(produce_api, "_set_status", lambda *a, **k: None)
    produce_api._free_gpu_for_render("p1")
    assert seen == ["lms", "llamacpp", "ollama"]


def test_free_gpu_respects_the_opt_out(monkeypatch):
    monkeypatch.setattr(produce_api.config_manager, "get",
                        lambda key, default=None: False if key == "produce_unload_llm" else default)
    monkeypatch.setattr(produce_api, "_stop_llamacpp", lambda p, c: pytest.fail("should not run"))
    produce_api._free_gpu_for_render("p1")


def test_lm_studio_unload_all(monkeypatch, ran):
    monkeypatch.setattr("integrations.llm.find_lms_binary", lambda: "lms.exe")
    _unload_lm_studio("p1", {})
    assert ran == [["lms.exe", "unload", "--all"]]


def test_llamacpp_on_another_machine_is_left_alone(monkeypatch, ran):
    monkeypatch.setattr(produce_api, "_find_buzzcode_binary", lambda: "buzzcode.exe")
    _stop_llamacpp("p1", {"llamacpp_url": "http://10.0.0.5:8089/v1"})
    assert ran == []


def _fake_psutil(monkeypatch, name, port=8089):
    killed = []

    class Proc:
        def __init__(self, pid):
            self.pid = pid

        def name(self):
            return name

        def children(self, recursive=False):
            return []

        def kill(self):
            killed.append(self.pid)

        def wait(self, timeout=None):
            return 0

    fake = SimpleNamespace(
        CONN_LISTEN="LISTEN",
        Error=Exception,
        Process=Proc,
        net_connections=lambda kind: [
            SimpleNamespace(status="LISTEN", laddr=SimpleNamespace(port=port), pid=4242),
            SimpleNamespace(status="LISTEN", laddr=SimpleNamespace(port=9999), pid=7),
        ],
    )
    monkeypatch.setitem(__import__("sys").modules, "psutil", fake)
    return killed


def test_llamacpp_stops_engine_then_kills_a_stray_server(monkeypatch, ran):
    monkeypatch.setattr(produce_api, "_find_buzzcode_binary", lambda: "buzzcode.exe")
    killed = _fake_psutil(monkeypatch, "llama-server.exe")
    _stop_llamacpp("p1", {"llamacpp_url": "http://127.0.0.1:8089/v1"})
    assert ran == [["buzzcode.exe", "engine", "stop"]]
    assert killed == [4242]


def test_llamacpp_never_kills_a_foreign_process_on_the_port(monkeypatch, ran):
    monkeypatch.setattr(produce_api, "_find_buzzcode_binary", lambda: None)
    killed = _fake_psutil(monkeypatch, "python.exe")
    _stop_llamacpp("p1", {"llamacpp_url": "http://localhost:8089/v1"})
    assert killed == []


def test_ollama_evicts_each_resident_model(monkeypatch):
    posted = []
    monkeypatch.setattr(produce_api.requests, "get", lambda url, timeout: SimpleNamespace(
        json=lambda: {"models": [{"name": "qwen3.5:9b"}, {"model": "llama3:8b"}]}))
    monkeypatch.setattr(produce_api.requests, "post",
                        lambda url, json, timeout: posted.append((url, json)))
    _unload_ollama("p1", {"ollama_url": "http://localhost:11434/v1"})
    assert posted == [
        ("http://localhost:11434/api/generate", {"model": "qwen3.5:9b", "keep_alive": 0}),
        ("http://localhost:11434/api/generate", {"model": "llama3:8b", "keep_alive": 0}),
    ]


def test_ollama_down_is_not_an_error(monkeypatch):
    def refuse(url, timeout):
        raise produce_api.requests.ConnectionError("refused")

    monkeypatch.setattr(produce_api.requests, "get", refuse)
    _unload_ollama("p1", {})
