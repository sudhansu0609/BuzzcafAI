"""`ensure_buzzedit_running` repairs BuzzEdit's own environment before trying
to launch it (2026-10-24): a disk-cleaner pass or an interrupted install can
leave its venv/engines/Electron build missing, and launching into that just
times out slowly instead of fixing anything. The repair time must not count
against the launch `timeout`."""
from app.api import produce_api
from app.services import app_envs


class _FakeClient:
    def __init__(self, state):
        self._state = state

    def health(self):
        return self._state["health"]


def test_ensure_buzzedit_running_repairs_the_env_before_launching(monkeypatch):
    state = {"health": None}
    monkeypatch.setattr(produce_api, "BuzzEditClient", lambda: _FakeClient(state))
    monkeypatch.setattr(produce_api.idle_offload, "mark_used", lambda *a, **k: None)
    monkeypatch.setattr(produce_api.time, "sleep", lambda s: None)

    monkeypatch.setattr(app_envs, "status", lambda app: {"app": app, "installed": True,
                                                          "missing": ["dist\\index.html"], "ok": False,
                                                          "repairing": False})
    repair_calls = []

    def fake_repair(app, **kw):
        repair_calls.append((app, kw))
        return {"status": "done", "exit_code": 0, "log_tail": ""}

    monkeypatch.setattr(app_envs, "repair", fake_repair)

    launch_calls = []

    def fake_launch():
        launch_calls.append(1)
        state["health"] = {"comfyui_connected": True}
        return True

    monkeypatch.setattr(produce_api, "launch_buzzedit_process", fake_launch)

    messages = []
    health = produce_api.ensure_buzzedit_running(
        status_callback=lambda msg, progress: messages.append(msg), timeout=5)

    assert health == {"comfyui_connected": True}
    assert repair_calls and repair_calls[0][0] == "BuzzEdit" and repair_calls[0][1]["wait"] is True
    assert launch_calls == [1]
    assert any("Repairing BuzzEdit" in m for m in messages)


def test_ensure_buzzedit_running_skips_repair_when_already_answering(monkeypatch):
    state = {"health": {"comfyui_connected": True}}
    monkeypatch.setattr(produce_api, "BuzzEditClient", lambda: _FakeClient(state))
    monkeypatch.setattr(produce_api.idle_offload, "mark_used", lambda *a, **k: None)

    checked = []
    monkeypatch.setattr(app_envs, "status", lambda app: checked.append(app))
    monkeypatch.setattr(app_envs, "repair", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("should not repair when BuzzEdit already answers")))

    health = produce_api.ensure_buzzedit_running(timeout=5)
    assert health == {"comfyui_connected": True}
    assert not checked  # never reached the app-env check
