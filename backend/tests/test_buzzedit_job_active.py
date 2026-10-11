"""`buzzedit_job_active` -- the health check's guard against loading an LLM
while BuzzEdit renders, including renders the Studio lost track of."""

from app.api import produce_api
from integrations.buzzedit_client import BuzzEditUnavailable


def _jobs(monkeypatch, answer):
    def fake_get_jobs(self):
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr(produce_api.BuzzEditClient, "get_jobs", fake_get_jobs)


def test_a_running_job_counts_as_busy(monkeypatch):
    _jobs(monkeypatch, {"is_running": True, "current_job_id": "job_85c82ec2", "jobs": []})
    assert produce_api.buzzedit_job_active() is True


def test_an_idle_scheduler_is_not_busy(monkeypatch):
    # `is_running` is the scheduler loop, true whenever BuzzEdit is up.
    _jobs(monkeypatch, {"is_running": True, "current_job_id": None, "jobs": []})
    assert produce_api.buzzedit_job_active() is False


def test_up_but_not_answering_counts_as_busy(monkeypatch):
    _jobs(monkeypatch, BuzzEditUnavailable("read timed out"))
    monkeypatch.setattr(produce_api, "buzzedit_base_url", lambda: "http://127.0.0.1:8099")
    assert produce_api.buzzedit_job_active() is True


def test_not_running_at_all_is_not_busy(monkeypatch):
    _jobs(monkeypatch, BuzzEditUnavailable("not reachable"))
    monkeypatch.setattr(produce_api, "buzzedit_base_url", lambda: None)
    assert produce_api.buzzedit_job_active() is False
