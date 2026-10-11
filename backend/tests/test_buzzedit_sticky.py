"""One production talks to one BuzzEdit: the sticky address, the queue
priority, and failing fast on a job BuzzEdit never had.

2026-10-03: a second BuzzEdit (a dev run on 8197) rewrote the port ledger
mid-production. The render was enqueued there, the GPU hand-over and the
progress polls went to the headless one on 8100, the second process died with
the job, and the Studio waited an hour for a job its BuzzEdit did not list.
"""

import pytest
import requests

from app.api import produce_api
from integrations import buzzedit_client


@pytest.fixture(autouse=True)
def _fresh_sticky(monkeypatch):
    monkeypatch.setattr(buzzedit_client, "_sticky_url", None)


def _discovery(monkeypatch, *answers):
    seen = list(answers)
    monkeypatch.setattr(buzzedit_client, "_discover", lambda: seen.pop(0) if len(seen) > 1 else seen[0])


class _Resp:
    status_code = 200

    def __init__(self, body=None):
        self._body = body or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def test_stays_on_the_first_buzzedit_when_the_ledger_changes(monkeypatch):
    _discovery(monkeypatch, "http://127.0.0.1:8100", "http://127.0.0.1:8197")
    urls = []
    monkeypatch.setattr(requests, "request", lambda method, url, **kw: urls.append(url) or _Resp({"jobs": []}))
    client = buzzedit_client.BuzzEditClient()
    client.get_jobs()
    buzzedit_client.BuzzEditClient().get_jobs()
    assert urls == ["http://127.0.0.1:8100/api/scheduler/jobs"] * 2


def test_a_refused_connection_finds_buzzedit_again(monkeypatch):
    _discovery(monkeypatch, "http://127.0.0.1:8100", "http://127.0.0.1:8101")

    def closed(method, url, **kw):
        raise requests.ConnectionError("refused")
    monkeypatch.setattr(requests, "request", closed)
    with pytest.raises(buzzedit_client.BuzzEditUnavailable):
        buzzedit_client.BuzzEditClient().get_jobs()
    assert buzzedit_client.base_url() == "http://127.0.0.1:8101"


def test_a_slow_buzzedit_keeps_its_address(monkeypatch):
    # Busy on the GPU is not gone: an in-flight render must not move.
    _discovery(monkeypatch, "http://127.0.0.1:8100", "http://127.0.0.1:8197")

    def slow(method, url, **kw):
        raise requests.ReadTimeout("busy")
    monkeypatch.setattr(requests, "request", slow)
    with pytest.raises(buzzedit_client.BuzzEditUnavailable):
        buzzedit_client.BuzzEditClient().get_jobs()
    assert buzzedit_client.base_url() == "http://127.0.0.1:8100"


@pytest.mark.parametrize("enqueue", [
    lambda c: c.enqueue_presentation("p1", {"genre": "horror"}),
    lambda c: c.enqueue_rerender("p1"),
])
def test_studio_renders_jump_the_buzzedit_queue(monkeypatch, enqueue):
    _discovery(monkeypatch, "http://127.0.0.1:8100")
    bodies = []
    monkeypatch.setattr(requests, "request",
                        lambda method, url, **kw: bodies.append(kw.get("json")) or _Resp({"job": {"id": "j"}}))
    enqueue(buzzedit_client.BuzzEditClient())
    assert bodies[0]["priority"] == "urgent"


def test_a_job_buzzedit_does_not_list_fails_fast(monkeypatch):
    monkeypatch.setattr(produce_api, "_JOB_MISSING_SECONDS", -1)
    monkeypatch.setattr(produce_api, "_POLL_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(produce_api.produce_queue, "cancel_requested", lambda project_id: False)
    monkeypatch.setattr(produce_api, "buzzedit_base_url", lambda: "http://127.0.0.1:8100")
    monkeypatch.setattr(produce_api.BuzzEditClient, "get_jobs", lambda self: {"jobs": [{"id": "job_other"}]})
    with pytest.raises(RuntimeError, match="has no render job job_f4e33112"):
        produce_api._await_render("proj", produce_api.BuzzEditClient(), "be1", "job_f4e33112")
