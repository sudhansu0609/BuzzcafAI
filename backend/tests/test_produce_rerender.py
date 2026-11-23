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


def test_a_failed_re_render_is_re_rendered_again_not_re_planned():
    # A re-render never saves a timeline, so its start is always after the
    # stamp; re-planning there threw away an hour of B-roll (674aefab).
    rerender = dict(JOB, job_type="presentation_render", created_at="2026-10-21T08:06:40")
    client = _Client({"status": "presented", "presented_at": "2026-10-21T07:51:29"})
    assert produce_api._rerender_possible(client, "a1", rerender)
    gone = _Client({"status": "analyzed", "presented_at": None})
    assert not produce_api._rerender_possible(gone, "a1", rerender)


def test_a_failed_re_render_of_a_rendered_edit_is_never_a_fresh_pass():
    # 2026-11-23 15:40: status "rendered" (after a picture top-up) was refused here, so the
    # queue ran a fresh pass that rebuilt the edit and dropped 97 added pictures.
    rerender = dict(JOB, job_type="presentation_render")
    rendered = _Client({"status": "rendered", "presented_at": "2026-11-23T11:00:00"})
    assert produce_api._rerender_possible(rendered, "a1", rerender)
    assert produce_api._rerender_possible(_Client({"status": "rendered"}), "a1", rerender)
    # BuzzEdit not answering: still the re-render (the attempt fails and is retried), never the pass.
    assert produce_api._rerender_possible(_Client(RuntimeError("down")), "a1", rerender)
