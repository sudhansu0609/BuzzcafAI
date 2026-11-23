"""`BuzzEditClient.transcribe` follows BuzzEdit's job once the POST outlives
its read timeout, instead of failing the production (the Oct 8 run: BuzzEdit
finished the cut six minutes after the Studio had given up on it)."""
import pytest
import requests

from integrations import buzzedit_client
from integrations.buzzedit_client import BuzzEditClient, BuzzEditJobFailed, BuzzEditTimeout, BuzzEditUnavailable


class _Resp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = str(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(buzzedit_client, "base_url", lambda: "http://buzzedit.test")
    monkeypatch.setattr(buzzedit_client.time, "sleep", lambda s: None)
    return BuzzEditClient()


def test_read_timeout_is_a_timeout_not_a_disappearance(client, monkeypatch):
    def slow(*args, **kwargs):
        raise requests.ReadTimeout("read timed out")
    monkeypatch.setattr(requests, "request", slow)
    with pytest.raises(BuzzEditTimeout):
        client._get("/api/health", timeout=(1, 1))
    # A refused connection is still the plain "gone" error.
    def refused(*args, **kwargs):
        raise requests.ConnectionError("refused")
    monkeypatch.setattr(requests, "request", refused)
    with pytest.raises(BuzzEditUnavailable) as exc:
        client._get("/api/health", timeout=(1, 1))
    assert not isinstance(exc.value, BuzzEditTimeout)


def test_transcribe_follows_the_job_after_the_post_times_out(client, monkeypatch):
    polls = iter([
        {"status": "running", "stage": "transcribing with Whisper (hi)"},
        {"status": "running", "stage": "planning the cut"},
        {"status": "completed", "stage": "saving the transcript"},
    ])
    seen_stages = []

    def post(path, body=None, timeout=None):
        assert path == "/api/transcription/transcribe"
        assert body["language"] == "hi"
        raise BuzzEditTimeout("still working")

    def get(path, timeout=None):
        assert path == "/api/transcription/status/trans_p1"
        return _Resp(200, next(polls))

    monkeypatch.setattr(client, "_post", post)
    monkeypatch.setattr(client, "_get", get)
    result = client.transcribe("p1", language="hi", progress_cb=seen_stages.append)
    assert result["status"] == "completed"
    assert seen_stages == ["transcribing with Whisper (hi)", "planning the cut"]


def test_a_failed_job_raises_with_buzzedits_reason(client, monkeypatch):
    monkeypatch.setattr(client, "_post", lambda *a, **k: (_ for _ in ()).throw(BuzzEditTimeout("busy")))
    monkeypatch.setattr(client, "_get", lambda path, timeout=None: _Resp(200, {"status": "failed", "error": "CUDA OOM"}))
    with pytest.raises(BuzzEditJobFailed, match="CUDA OOM"):
        client.transcribe("p1")


def test_a_lost_job_is_resolved_from_the_project(client, monkeypatch):
    monkeypatch.setattr(client, "_post", lambda *a, **k: (_ for _ in ()).throw(BuzzEditTimeout("busy")))

    def get(path, timeout=None):
        if path.startswith("/api/transcription/status/"):
            return _Resp(404, {"detail": "Job not found"})
        assert path == "/api/projects/p1"
        return _Resp(200, {"id": "p1", "status": "transcribed",
                           "transcript": {"segments": [{"text": "hello"}], "language": "hi"}})

    monkeypatch.setattr(client, "_get", get)
    assert client.transcribe("p1")["recovered"] is True

    def get_untranscribed(path, timeout=None):
        if path.startswith("/api/transcription/status/"):
            return _Resp(404, {"detail": "Job not found"})
        return _Resp(200, {"id": "p1", "status": "imported", "transcript": {}})

    monkeypatch.setattr(client, "_get", get_untranscribed)
    with pytest.raises(BuzzEditUnavailable):
        client.transcribe("p1")


def test_a_stuck_stage_ends_the_wait(client, monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(buzzedit_client.time, "monotonic", lambda: clock["t"])

    def get(path, timeout=None):
        clock["t"] += 600.0
        return _Resp(200, {"status": "running", "stage": "planning the cut"})

    monkeypatch.setattr(client, "_get", get)
    with pytest.raises(BuzzEditJobFailed, match="no progress"):
        client.wait_for_transcription("p1", stall_seconds=1800, max_seconds=36000, poll_seconds=0)


def test_an_immediate_answer_still_works(client, monkeypatch):
    monkeypatch.setattr(client, "_post", lambda path, body=None, timeout=None: _Resp(200, {"status": "completed"}))
    assert client.transcribe("p1", language="hi")["status"] == "completed"
    monkeypatch.setattr(client, "_post", lambda path, body=None, timeout=None: _Resp(500, {"detail": "boom"}))
    with pytest.raises(BuzzEditJobFailed, match="boom"):
        client.transcribe("p1")


def test_a_busy_buzzedit_does_not_count_as_gone(client, monkeypatch):
    """2026-10-20: BuzzEdit answered its status polls late (an ffmpeg join on
    the event loop) and the Studio counted the read timeouts towards the
    unreachable grace. A timeout means busy: the wait goes on until the job
    moves, bounded only by the stall ceiling."""
    polls = iter([
        BuzzEditTimeout("read timed out"),
        BuzzEditTimeout("read timed out"),
        BuzzEditTimeout("read timed out"),
        {"status": "running", "stage": "verifying the cut"},
        BuzzEditTimeout("read timed out"),
        {"status": "completed", "stage": "saving the transcript"},
    ])

    def get(path, timeout=None):
        nxt = next(polls)
        if isinstance(nxt, Exception):
            raise nxt
        return _Resp(200, nxt)

    monkeypatch.setattr(client, "_get", get)
    monkeypatch.setattr(buzzedit_client, "UNREACHABLE_GRACE_SECONDS", 0)  # would end it at once if counted
    result = client.wait_for_transcription("p1", stall_seconds=3600, max_seconds=7200)
    assert result["status"] == "completed"


def test_a_refused_connection_still_ends_the_wait_after_the_grace(client, monkeypatch):
    def get(path, timeout=None):
        raise BuzzEditUnavailable("refused")

    monkeypatch.setattr(client, "_get", get)
    monkeypatch.setattr(buzzedit_client, "UNREACHABLE_GRACE_SECONDS", -1)
    with pytest.raises(BuzzEditUnavailable):
        client.wait_for_transcription("p1")


def test_every_answer_is_remembered(monkeypatch):
    """`seconds_since_answer` is what the watchdogs read to tell busy from hung."""
    monkeypatch.setattr(buzzedit_client, "base_url", lambda: "http://buzzedit.test")
    monkeypatch.setattr(buzzedit_client, "_last_answer_at", None)
    assert buzzedit_client.seconds_since_answer() is None
    monkeypatch.setattr(requests, "request", lambda *a, **k: _Resp(200, {"ok": True}))
    BuzzEditClient()._get("/api/health", timeout=(1, 1))
    assert buzzedit_client.answered_within(5)
    monkeypatch.setattr(buzzedit_client, "_last_answer_at", buzzedit_client.time.monotonic() - 100)
    assert not buzzedit_client.answered_within(5)
