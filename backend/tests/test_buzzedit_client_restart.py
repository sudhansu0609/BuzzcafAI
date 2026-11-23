"""`BuzzEditClient.narration_busy` and `.set_supervisor_parent`
(STUDIO_DIRECTOR_PLAN.md enhancement 2/4/5): the Studio's own holds for a
busy BuzzEdit, and re-parenting a headless BuzzEdit's Electron watchdog."""
import requests

from integrations.buzzedit_client import BuzzEditClient


class _FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")


def test_narration_busy_true_when_buzzedit_reports_it(monkeypatch):
    client = BuzzEditClient()
    monkeypatch.setattr(client, "_get", lambda path, timeout=None: _FakeResponse(200, {"busy": True}))
    assert client.narration_busy() is True


def test_narration_busy_false_when_not_running(monkeypatch):
    client = BuzzEditClient()
    monkeypatch.setattr(client, "_get", lambda path, timeout=None: _FakeResponse(200, {"busy": False}))
    assert client.narration_busy() is False


def test_narration_busy_counts_a_slow_answer_as_busy(monkeypatch):
    client = BuzzEditClient()

    def fake_get(path, timeout=None):
        raise requests.exceptions.Timeout("slow")

    monkeypatch.setattr(client, "_get", fake_get)
    assert client.narration_busy() is True


def test_narration_busy_false_when_buzzedit_is_not_running(monkeypatch):
    client = BuzzEditClient()

    def fake_get(path, timeout=None):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(client, "_get", fake_get)
    assert client.narration_busy() is False


def test_set_supervisor_parent_posts_the_pid(monkeypatch):
    client = BuzzEditClient()
    seen = {}

    def fake_post(path, json_body=None, timeout=None):
        seen["path"] = path
        seen["body"] = json_body
        return _FakeResponse(200, {"pid": json_body["pid"]})

    monkeypatch.setattr(client, "_post", fake_post)
    result = client.set_supervisor_parent(4242)
    assert result == {"pid": 4242}
    assert seen == {"path": "/api/supervisor/parent", "body": {"pid": 4242}}


def test_set_supervisor_parent_none_on_failure(monkeypatch):
    client = BuzzEditClient()

    def fake_post(path, json_body=None, timeout=None):
        raise RuntimeError("down")

    monkeypatch.setattr(client, "_post", fake_post)
    assert client.set_supervisor_parent(4242) is None
