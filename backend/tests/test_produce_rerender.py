"""A retry after a render that died re-renders the saved edit; it only runs the
whole presentation pass again when that job never saved its timeline."""
from app.api import produce_api


class _Client:
    def __init__(self, project):
        self.project = project

    def get_project(self, _pid):
        if isinstance(self.project, Exception):
            raise self.project
        return self.project


JOB = {"id": "job_1", "status": "failed", "created_at": "2026-10-01T16:52:51.123456"}


def test_a_timeline_saved_by_the_failed_job_is_re_rendered():
    client = _Client({"status": "presented", "presented_at": "2026-10-01T17:17:10"})
    assert produce_api._rerender_possible(client, "a1", JOB)


def test_an_older_timeline_or_an_unfinished_pass_runs_the_pass_again():
    older = _Client({"status": "presented", "presented_at": "2026-10-01T14:30:00"})
    assert not produce_api._rerender_possible(older, "a1", JOB)
    not_saved = _Client({"status": "analyzed", "presented_at": None})
    assert not produce_api._rerender_possible(not_saved, "a1", JOB)
    rendered = _Client({"status": "rendered", "presented_at": "2026-10-01T17:17:10"})
    assert not produce_api._rerender_possible(rendered, "a1", JOB)


def test_buzzedit_unreachable_falls_back_to_the_pass():
    assert not produce_api._rerender_possible(_Client(RuntimeError("down")), "a1", JOB)
