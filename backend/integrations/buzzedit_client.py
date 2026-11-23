"""
Talk to BuzzEdit, the ComfyUI-backed auto-editor that turns a recording plus
an annotated script into a rendered video.

BuzzcafAI prefers port 8099 and BuzzEdit prefers port 8100, but either can
land on the other's port --
`discover()` is how one finds the other without ever hardcoding a port (see
`integrations/buzzcaf_ports.py`; rule 4 there, the health-body identity check,
is what tells the two apart on a collision). This client is the
BuzzcafAI -> BuzzEdit side of that bridge: it wraps the handful of BuzzEdit
HTTP endpoints the `produce_video` orchestrator (`app/api/produce_api.py`)
needs, and nothing else.

Best-effort by design, same philosophy as `sentinel_client.py`: BuzzEdit not
running, not reachable, or slow must produce one clear exception
(`BuzzEditUnavailable`) rather than a raw `requests` traceback or a hang.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger("buzzcaf_ai.buzzedit_client")

#: How long `transcribe` waits on the POST itself before following the job.
TRANSCRIBE_FIRST_WAIT_SECONDS = 20 * 60
#: A transcription whose reported stage has not changed for this long is stuck.
TRANSCRIBE_STALL_SECONDS = 2 * 60 * 60
#: The outer ceiling on one transcription, however long the recording.
TRANSCRIBE_MAX_SECONDS = 8 * 60 * 60
#: How long polls may be *refused* (no process on the port) before BuzzEdit
#: counts as gone. A read timeout is not this: a busy BuzzEdit still accepts
#: the connection, and a wait never ends on timeouts alone (see
#: `wait_for_transcription`). Long enough for a BuzzEdit that crashed and is
#: being relaunched by the keep-alive to come back on its own.
UNREACHABLE_GRACE_SECONDS = 10 * 60
#: An audio job (a voice conversion) whose progress and message have not
#: changed for this long is stuck. There is no ceiling on the work itself.
AUDIO_JOB_STALL_SECONDS = 30 * 60


class BuzzEditUnavailable(Exception):
    """BuzzEdit could not be found, or did not answer."""


class BuzzEditTimeout(BuzzEditUnavailable):
    """BuzzEdit accepted the request but had not answered when the read
    timeout ran out. It is very likely still working on it -- a 37-minute
    recording's transcription plus the fluency and verify passes took 36
    minutes on the 5060 Ti -- so callers follow the job instead of failing."""


class BuzzEditJobFailed(RuntimeError):
    """BuzzEdit reported that the job it was running failed."""


#: The BuzzEdit every Studio call goes to, shared by all clients. Discovery
#: follows the port ledger, and a second BuzzEdit (a dev run) that rewrote it
#: mid-production got the render enqueued on it, while the GPU hand-over and
#: the progress polls went to the other one -- the job died with the second
#: process and the Studio waited an hour on a job its BuzzEdit never had.
#: So once found, an instance keeps every call until it stops accepting
#: connections. A read timeout does not count: a BuzzEdit busy on the GPU
#: answers slowly, and that must not move an in-flight render.
_sticky_lock = threading.Lock()
_sticky_url: Optional[str] = None

#: When BuzzEdit last answered any request at all (`time.monotonic()`), or
#: None before the first answer. The watchdogs read it: a BuzzEdit that
#: answered a minute ago and times out now is busy, not hung.
_last_answer_at: Optional[float] = None


def _answered() -> None:
    global _last_answer_at
    _last_answer_at = time.monotonic()


def seconds_since_answer() -> Optional[float]:
    """How long since BuzzEdit last answered the Studio, or None if it never has
    in this process."""
    return None if _last_answer_at is None else time.monotonic() - _last_answer_at


def answered_within(seconds: float) -> bool:
    since = seconds_since_answer()
    return since is not None and since <= seconds


#: BuzzEdit's scheduler takes pending jobs by priority (urgent, normal, low),
#: then age. A Studio production goes ahead of anything queued from
#: BuzzEdit's own UI; a job already rendering is never pre-empted.
STUDIO_JOB_PRIORITY = "urgent"


def _detail(resp: requests.Response) -> str:
    """The `detail` of an error answer, else the start of its body."""
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:300]
    return str(body.get("detail") or "") if isinstance(body, dict) else str(body)[:300]


def _discover() -> Optional[str]:
    from integrations import buzzcaf_ports
    from core.config import config_manager

    env_url = os.environ.get("BUZZEDIT_URL") or config_manager.get("BUZZEDIT_URL")
    return buzzcaf_ports.discover("buzzedit", 8100, health_path="/api/health", env_url=env_url)


def base_url() -> Optional[str]:
    """Where BuzzEdit is listening, or None. Ledger discovery, not a guess.

    `BUZZEDIT_URL` (env, or the `buzzedit_url` config key) is an explicit
    override for an unusual setup; the normal path is the shared port ledger
    both apps publish to (`buzzcaf_ports.discover`), which resolves the 8099
    collision between the two backends by checking who a listener actually
    says it is, rather than trusting whichever process got there first.
    Sticky: see `_sticky_url`.
    """
    global _sticky_url
    with _sticky_lock:
        if _sticky_url:
            return _sticky_url
    found = _discover()
    if found:
        with _sticky_lock:
            if not _sticky_url:
                _sticky_url = found
                logger.info("BuzzEdit found at %s; the Studio stays on it while it answers.", found)
            return _sticky_url
    return None


def _unstick(url: str) -> None:
    """`url` refused a connection: BuzzEdit closed or moved. Discover again."""
    global _sticky_url
    with _sticky_lock:
        if _sticky_url == url:
            _sticky_url = None
            logger.info("BuzzEdit at %s stopped accepting connections; looking for it again.", url)


class BuzzEditClient:
    """One method per BuzzEdit endpoint `produce_video` needs.

    Every client shares the sticky address from `base_url()`, so one
    production talks to one BuzzEdit from import to render.
    """

    def __init__(self, timeout: Tuple[int, int] = (5, 120)):
        self.timeout = timeout

    def _base(self) -> str:
        url = base_url()
        if not url:
            raise BuzzEditUnavailable(
                "BuzzEdit is not reachable (not running, or not discoverable on the shared port ledger)."
            )
        return url

    def _send(self, method: str, path: str, timeout: Optional[Tuple[int, int]], **kwargs: Any) -> requests.Response:
        base = self._base()
        try:
            resp = requests.request(method, f"{base}{path}", timeout=timeout or self.timeout, **kwargs)
            _answered()
            return resp
        except requests.ReadTimeout as exc:
            # Connected and sent, no answer in time: BuzzEdit is busy, not gone.
            raise BuzzEditTimeout(f"BuzzEdit did not answer {method} {path}: {exc}") from exc
        except requests.ConnectionError as exc:
            _unstick(base)
            raise BuzzEditUnavailable(f"BuzzEdit did not answer {method} {path}: {exc}") from exc
        except requests.RequestException as exc:
            raise BuzzEditUnavailable(f"BuzzEdit did not answer {method} {path}: {exc}") from exc

    def _get(self, path: str, timeout: Optional[Tuple[int, int]] = None) -> requests.Response:
        return self._send("GET", path, timeout)

    def _post(
        self, path: str, json_body: Optional[Dict[str, Any]] = None, timeout: Optional[Tuple[int, int]] = None
    ) -> requests.Response:
        return self._send("POST", path, timeout, json=json_body or {})

    def _put(
        self, path: str, json_body: Optional[Dict[str, Any]] = None, timeout: Optional[Tuple[int, int]] = None
    ) -> requests.Response:
        return self._send("PUT", path, timeout, json=json_body or {})

    # ------------------------------------------------------------- health

    def health(self) -> Optional[Dict[str, Any]]:
        """`GET /api/health`, or None on any failure -- best-effort, never raises."""
        try:
            resp = self._get("/api/health", timeout=(3, 5))
            if resp.status_code != 200:
                return None
            return resp.json()
        except Exception as exc:
            logger.debug("buzzedit health check failed: %s", exc)
            return None

    def comfyui_online(self) -> bool:
        """`comfyui_connected` from BuzzEdit's own live probe of ComfyUI."""
        health = self.health()
        return bool(health and health.get("comfyui_connected"))

    # ----------------------------------------------------------- projects

    def import_recording(self, path: str) -> Dict[str, Any]:
        """`POST /api/projects/import_path` -> the full BuzzEdit Project dict
        (`.id` is what every later call needs)."""
        # BuzzEdit hard-links a recording on its own drive (instant) but copies
        # one from another drive, and a multi-GB take can take minutes.
        resp = self._post("/api/projects/import_path", {"path": path}, timeout=(5, 1800))
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail")
            except ValueError:
                detail = resp.text[:300]
            raise RuntimeError(f"BuzzEdit could not import the recording: {detail or resp.status_code}")
        return resp.json()

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        resp = self._get(f"/api/projects/{project_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------- eye contact
    #
    # BuzzEdit's teleprompter gaze correction (routes/eyecontact.py): renders a
    # corrected copy of a library clip on the GPU and swaps it in everywhere
    # the original was used, keeping the original for a revert.

    def eye_contact_available(self) -> Dict[str, Any]:
        """`GET /api/eyecontact/available` -> `{available, reason}`."""
        resp = self._get("/api/eyecontact/available", timeout=(5, 30))
        resp.raise_for_status()
        return resp.json()

    def eye_contact_settings(self) -> Dict[str, Any]:
        """BuzzEdit's saved prompter setup (the defaults every run starts from)."""
        resp = self._get("/api/eyecontact/settings", timeout=(5, 15))
        resp.raise_for_status()
        return resp.json()

    def start_eye_contact(self, project_id: str, media_id: str, setup: Dict[str, Any]) -> str:
        """Start correcting one clip; returns the job id (an existing job's, if
        that clip is already being corrected)."""
        resp = self._post(f"/api/eyecontact/projects/{project_id}/media/{media_id}", setup, timeout=(5, 30))
        resp.raise_for_status()
        return resp.json()["job_id"]

    def start_eye_contact_analyse(self, project_id: str, media_id: str, setup: Dict[str, Any]) -> str:
        """`POST /api/eyecontact/projects/{id}/media/{mid}/analyse`: track the whole recording
        and plan it without rendering. Followed with `eye_contact_status`; the result is
        the measured numbers (where the prompter is, how much looks into the lens, how far
        the eyes move) and the landmark cache every preview and the full run reuse."""
        resp = self._post(f"/api/eyecontact/projects/{project_id}/media/{media_id}/analyse", setup, timeout=(5, 30))
        if resp.status_code >= 400:
            raise BuzzEditJobFailed(f"BuzzEdit could not analyse the recording: {_detail(resp) or resp.status_code}")
        return resp.json()["job_id"]

    def start_eye_contact_preview(self, project_id: str, media_id: str, setup: Dict[str, Any],
                                  start_s: float, duration_s: float) -> str:
        """`POST .../preview`: correct `duration_s` seconds from `start_s` into a before/after
        pair in BuzzEdit's preview cache. The finished job's result carries `before_path`
        and `after_path`."""
        body = {**setup, "start_s": float(start_s), "duration_s": float(duration_s)}
        resp = self._post(f"/api/eyecontact/projects/{project_id}/media/{media_id}/preview", body, timeout=(5, 30))
        if resp.status_code >= 400:
            raise BuzzEditJobFailed(f"BuzzEdit could not start the preview: {_detail(resp) or resp.status_code}")
        return resp.json()["job_id"]

    def eye_contact_status(self, job_id: str) -> Dict[str, Any]:
        """`{status: queued|running|completed|failed|cancelled, progress, stage, result, error}`."""
        resp = self._get(f"/api/eyecontact/status/{job_id}", timeout=(5, 15))
        resp.raise_for_status()
        return resp.json()

    def revert_eye_contact(self, project_id: str, media_id: str) -> Dict[str, Any]:
        resp = self._post(f"/api/eyecontact/projects/{project_id}/media/{media_id}/revert", {}, timeout=(5, 30))
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------- transcription

    def transcribe(self, project_id: str, language: Optional[str] = None,
                   precut: Optional[bool] = None, vocabulary: Optional[list] = None,
                   glossary: Optional[str] = None,
                   auto_edit: Optional[Dict[str, Any]] = None,
                   genre: Optional[str] = None,
                   speaker_style: Optional[str] = None,
                   progress_cb: Optional[Callable[[str], None]] = None,
                   first_wait_seconds: int = TRANSCRIBE_FIRST_WAIT_SECONDS,
                   stall_seconds: int = TRANSCRIBE_STALL_SECONDS,
                   max_seconds: int = TRANSCRIBE_MAX_SECONDS) -> Dict[str, Any]:
        """`POST /api/transcription/transcribe`, then follow the job.

        BuzzEdit answers the POST only when Whisper, the auto-edit planning,
        the fluency/verify passes and the cut check have all finished -- on
        a 37-minute recording that was 36 minutes, past the 30-minute read
        timeout this call used to have, and the Studio marked the run failed
        while BuzzEdit finished the cut six minutes later. So the POST is
        waited on for `first_wait_seconds` and, when it has not answered by
        then, `wait_for_transcription` follows BuzzEdit's own job record
        (`GET /api/transcription/status/trans_<id>`, which the route marks
        completed or failed) until it is done. There is no fixed ceiling on
        the work itself: only `stall_seconds` with no sign of life from the
        job (its stage not changing, on a BuzzEdit that reports stages) and
        a very generous `max_seconds` end the wait.

        `language` pins Whisper's language ("hi" for every channel here:
        auto-detection called a Hinglish take Urdu and wrote the transcript
        in Urdu script); None lets BuzzEdit auto-detect.

        `precut=True` says the recording is already cut: BuzzEdit skips its
        fumble/silence auto-edit and keeps every frame (stored on the BuzzEdit
        project, so its later passes honour it too).

        `vocabulary` is a list of words the written script uses (proper nouns,
        brand terms) that Whisper's own vocabulary would not favour --
        BuzzEdit ignores an unknown field, so an older BuzzEdit is unaffected.
        `glossary` is the channel key (e.g. `"life3baje"`) BuzzEdit can use to
        pick its own per-brand hints, if it has any.

        `auto_edit` is the channel profile's pacing block
        (`max_pause_seconds`, `pause_padding_seconds`, `fumble_aggressiveness`);
        its keys are sent as top-level fields, which BuzzEdit stores on the
        project like `precut`. An older BuzzEdit ignores them.

        `genre` is the channel profile's genre. When the channel sends no
        pacing, BuzzEdit paces the cut by genre -- horror keeps its pauses --
        and a named genre spares it guessing from the transcript.

        `speaker_style` is the creator's style summary (his fixed opening line,
        his voice, habitual phrases, words he never uses) for BuzzEdit's AI cut
        editor, which stores it on the project so a re-cut reuses it. An older
        BuzzEdit ignores it.
        """
        body: Dict[str, Any] = {"project_id": project_id}
        if language is not None:
            body["language"] = language
        if precut is not None:
            body["precut"] = precut
        if vocabulary:
            body["vocabulary"] = vocabulary
        if glossary:
            body["glossary"] = glossary
        for key, value in (auto_edit or {}).items():
            if value is not None:
                body[key] = value
        if genre:
            body["genre"] = genre
        if speaker_style:
            body["speaker_style"] = speaker_style
        started = time.monotonic()
        try:
            resp = self._post("/api/transcription/transcribe", body, timeout=(10, first_wait_seconds))
        except BuzzEditTimeout:
            logger.info("BuzzEdit is still transcribing %s after %ds; following its job instead of waiting "
                        "on the request.", project_id, first_wait_seconds)
            return self.wait_for_transcription(project_id, progress_cb=progress_cb, stall_seconds=stall_seconds,
                                               max_seconds=max_seconds, started=started)
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail")
            except ValueError:
                detail = resp.text[:300]
            raise BuzzEditJobFailed(f"BuzzEdit could not transcribe the recording: {detail or resp.status_code}")
        return resp.json()

    def transcription_status(self, project_id: str) -> Optional[Dict[str, Any]]:
        """`GET /api/transcription/status/trans_<project_id>` -- BuzzEdit's in-memory
        record of the transcription it is running (or ran) for this project:
        `{status: running|completed|failed, stage?, updated_at?, error?}`.
        None when BuzzEdit has no such job (it never ran one, or BuzzEdit was
        restarted since; the project itself still says whether it is
        transcribed, see `is_transcribed`)."""
        resp = self._get(f"/api/transcription/status/trans_{project_id}", timeout=(5, 30))
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def transcription_jobs(self) -> list:
        """`GET /api/transcription/jobs` -> the transcriptions BuzzEdit is running
        right now. [] on an older BuzzEdit without the endpoint."""
        resp = self._get("/api/transcription/jobs", timeout=(5, 15))
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        jobs = data.get("jobs") if isinstance(data, dict) else data
        return [j for j in (jobs or []) if isinstance(j, dict) and j.get("status") == "running"]

    def recut(self, project_id: str, progress_cb: Optional[Callable[[str], None]] = None,
              first_wait_seconds: int = TRANSCRIBE_FIRST_WAIT_SECONDS,
              stall_seconds: int = TRANSCRIBE_STALL_SECONDS,
              max_seconds: int = TRANSCRIBE_MAX_SECONDS) -> Dict[str, Any]:
        """`POST /api/transcription/{id}/recut`: plan the cut again from the
        words BuzzEdit already has, without Whisper. Followed exactly like a
        transcription (same `trans_<id>` job). Used when the cut rules changed
        after a production, since a restart otherwise reuses the old cut."""
        started = time.monotonic()
        try:
            resp = self._post(f"/api/transcription/{project_id}/recut", {}, timeout=(10, first_wait_seconds))
        except BuzzEditTimeout:
            logger.info("buzzedit recut(%s): still planning after %ds; following the job.",
                        project_id, first_wait_seconds)
            return self.wait_for_transcription(project_id, progress_cb=progress_cb, stall_seconds=stall_seconds,
                                               max_seconds=max_seconds, started=started)
        return resp

    def is_transcribed(self, project_id: str) -> bool:
        """Whether BuzzEdit's project already holds a finished transcription
        (its `status` is `transcribed` and it has transcript segments). This
        is what a transcription that finished after the Studio stopped
        waiting leaves behind -- and what lets a retry skip re-transcribing."""
        try:
            data = self.get_project(project_id)
        except BuzzEditUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - a malformed answer reads as "not yet"
            logger.debug("buzzedit get_project(%s) failed: %s", project_id, exc)
            return False
        if not data:
            return False
        transcript = data.get("transcript") or {}
        has_words = bool(transcript.get("segments") or transcript.get("words"))
        return str(data.get("status") or "") in ("transcribed", "presented", "rendered") and has_words

    def wait_for_transcription(self, project_id: str, progress_cb: Optional[Callable[[str], None]] = None,
                               stall_seconds: int = TRANSCRIBE_STALL_SECONDS,
                               max_seconds: int = TRANSCRIBE_MAX_SECONDS,
                               poll_seconds: float = 15.0,
                               started: Optional[float] = None) -> Dict[str, Any]:
        """Follow BuzzEdit's transcription job for `project_id` until it is
        completed (returns the job record) or failed (`BuzzEditJobFailed`).

        A BuzzEdit that stops answering for `UNREACHABLE_GRACE_SECONDS`
        raises `BuzzEditUnavailable` so the caller can relaunch it and
        decide whether to transcribe again. A job BuzzEdit no longer knows
        (404: it was restarted) is resolved from the project itself: already
        transcribed means done, otherwise `BuzzEditUnavailable` as well.
        """
        started = time.monotonic() if started is None else started
        last_stage: Optional[str] = None
        last_change = time.monotonic()
        unreachable_since: Optional[float] = None
        while True:
            try:
                job = self.transcription_status(project_id)
                unreachable_since = None
            except BuzzEditTimeout as exc:
                # Connected, no answer in time: BuzzEdit is busy (ffmpeg, the
                # planner, a save), not gone. That never counts towards the
                # unreachable grace -- only the stall and the ceiling end a
                # wait on a BuzzEdit that still accepts connections.
                logger.info("BuzzEdit is busy (%s); still following the transcription of %s.", exc, project_id)
                if time.monotonic() - last_change > stall_seconds:
                    raise BuzzEditJobFailed(
                        f"BuzzEdit has not answered about the transcription of {project_id} for "
                        f"{int(stall_seconds // 60)} minutes.") from exc
                time.sleep(poll_seconds)
                continue
            except BuzzEditUnavailable as exc:
                now = time.monotonic()
                unreachable_since = unreachable_since or now
                if now - unreachable_since > UNREACHABLE_GRACE_SECONDS:
                    raise BuzzEditUnavailable(
                        f"BuzzEdit stopped answering while transcribing {project_id}: {exc}") from exc
                logger.warning("BuzzEdit did not answer the transcription poll (%s); trying again.", exc)
                time.sleep(poll_seconds)
                continue
            except Exception as exc:  # noqa: BLE001 - one bad poll must not end the wait
                logger.warning("Transcription poll for %s failed (%s); trying again.", project_id, exc)
                time.sleep(poll_seconds)
                continue

            if job is None:
                if self.is_transcribed(project_id):
                    logger.info("BuzzEdit has no job record for %s but the project is transcribed; done.",
                                project_id)
                    return {"status": "completed", "recovered": True}
                raise BuzzEditUnavailable(
                    f"BuzzEdit no longer has the transcription job for {project_id} (restarted?) and the "
                    "project is not transcribed.")

            status = str(job.get("status") or "")
            if status == "completed":
                return job
            if status == "failed":
                raise BuzzEditJobFailed(
                    f"BuzzEdit's transcription failed: {job.get('error') or 'no error detail given'}")

            stage = str(job.get("stage") or job.get("message") or "")
            if stage and stage != last_stage:
                last_stage, last_change = stage, time.monotonic()
                if progress_cb:
                    try:
                        progress_cb(stage)
                    except Exception:  # noqa: BLE001 - status text must never end the wait
                        pass
            elapsed = time.monotonic() - started
            # A BuzzEdit that reports stages shows it is alive by moving between
            # them; one that does not gets the long ceiling only.
            if last_stage and time.monotonic() - last_change > stall_seconds:
                raise BuzzEditJobFailed(
                    f"BuzzEdit's transcription has shown no progress for {int(stall_seconds // 60)} minutes "
                    f"(stuck at '{last_stage}').")
            if elapsed > max_seconds:
                raise BuzzEditJobFailed(
                    f"BuzzEdit's transcription is still running after {int(elapsed // 60)} minutes; giving up.")
            time.sleep(poll_seconds)

    def get_transcript_words(self, project_id: str) -> list:
        """`GET /api/transcription/{id}/transcript` flattened to its words
        (`{word, start, end, word_native?}`), in spoken order. Includes every
        word Whisper heard, cut or kept -- `get_kept_words` is almost always
        what a post-cut caller wants instead."""
        resp = self._get(f"/api/transcription/{project_id}/transcript")
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        words: list = []
        for segment in (resp.json() or {}).get("segments") or []:
            words.extend(segment.get("words") or [])
        return words

    def get_kept_words(self, project_id: str) -> list:
        """`GET /api/projects/{id}/kept_words`: only the words that survived
        the cut, in programme order, each `{word, word_native, start, end,
        tl_start, tl_end}` -- `start`/`end` are source (original recording)
        time, `tl_start`/`tl_end` are where the word lands in the edited
        programme (None where BuzzEdit could not place it, e.g. a dropped
        sliver). Falls back to every transcribed word (`get_transcript_words`)
        on a 404, for an older BuzzEdit that predates this endpoint."""
        resp = self._get(f"/api/projects/{project_id}/kept_words")
        if resp.status_code == 404:
            logger.info("BuzzEdit has no /kept_words endpoint; falling back to the full transcript.")
            return self.get_transcript_words(project_id)
        resp.raise_for_status()
        return (resp.json() or {}).get("words") or []

    # -------------------------------------------------------------- script

    def set_script(self, project_id: str, text: str) -> Dict[str, Any]:
        """`PUT /api/projects/{id}/script`. Aligns to the transcript if one
        exists yet, else stores the text un-aligned."""
        resp = self._put(f"/api/projects/{project_id}/script", {"text": text}, timeout=(5, 60))
        resp.raise_for_status()
        return resp.json()

    def cut_program(self, project_id: str, start_frame: int, end_frame: int) -> Dict[str, Any]:
        """`POST /api/timeline/{id}/program/cut`: delete a span of the edited
        programme on every track (programme frames). It is kept as a manual
        cut, so a later re-cut of the words does not bring it back -- how the
        Shorts recorded before a long video are taken off it."""
        resp = self._post(f"/api/timeline/{project_id}/program/cut",
                          {"start_frame": int(start_frame), "end_frame": int(end_frame)}, timeout=(5, 120))
        if resp.status_code >= 400:
            raise RuntimeError(f"BuzzEdit could not cut the programme: {_detail(resp)}")
        return resp.json()

    def get_script(self, project_id: str) -> Dict[str, Any]:
        """`GET /api/projects/{id}/script`.

        Note: the response's `paragraphs` field is an integer count, not a
        list of paragraph objects -- do not index it.
        """
        resp = self._get(f"/api/projects/{project_id}/script")
        resp.raise_for_status()
        return resp.json()

    # -------------------------------------------------------- stock keys

    def get_stock_keys(self) -> Dict[str, Any]:
        """`GET /api/settings/stock_keys`: BuzzEdit's free-stock (Pexels /
        Pixabay) keys, masked to their last 4 characters plus a `<name>_set`
        flag each. Never the keys themselves."""
        resp = self._get("/api/settings/stock_keys", timeout=(5, 15))
        resp.raise_for_status()
        return resp.json()

    def set_stock_keys(self, pexels_api_key: Optional[str] = None,
                       pixabay_api_key: Optional[str] = None) -> Dict[str, Any]:
        """`PUT /api/settings/stock_keys`. A key left None is left alone on
        BuzzEdit's side; "" clears it. Returns the masked state."""
        body: Dict[str, Any] = {}
        if pexels_api_key is not None:
            body["pexels_api_key"] = pexels_api_key
        if pixabay_api_key is not None:
            body["pixabay_api_key"] = pixabay_api_key
        resp = self._put("/api/settings/stock_keys", body, timeout=(5, 15))
        resp.raise_for_status()
        return resp.json()

    def set_auto_cut_editor(self, base_url: str, api_key: str) -> Dict[str, Any]:
        """`PUT /api/settings/auto_cut_editor`: the Claude proxy BuzzEdit's AI
        cut editor calls. Without it BuzzEdit logs "no key for the Claude
        proxy" and falls back to the classic planner plus its slow local
        fluency/verify passes. The key is stored on BuzzEdit's side (never
        echoed back), the same way the Pixabay key is."""
        resp = self._put("/api/settings/auto_cut_editor", {"base_url": base_url, "api_key": api_key},
                         timeout=(5, 15))
        resp.raise_for_status()
        return resp.json()

    def set_clip_generation(self, mode: str) -> Dict[str, Any]:
        """`PUT /api/settings/clip_generation`: how BuzzEdit generates its
        clips -- "classic" (832x480, fast) or "hq" (1024x576 delivered at
        1080p, slower). Returns BuzzEdit's stored state."""
        resp = self._put("/api/settings/clip_generation", {"mode": mode}, timeout=(5, 15))
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------ audio racks
    #
    # BuzzEdit's whole-rack audio presets (its routes/audio.py, AUDIO_SUITE_PLAN.md
    # brief A5). Best-effort, like the clip-generation push: a failure is logged
    # and answered with None, and the render keeps the rack it already has.

    def list_rack_presets(self) -> Optional[Dict[str, Any]]:
        """`GET /api/audio/rack_presets` -> `{name: {effects, created, note}}`,
        or None when BuzzEdit did not answer."""
        try:
            resp = self._get("/api/audio/rack_presets", timeout=(5, 15))
            resp.raise_for_status()
            presets = resp.json().get("presets")
            return presets if isinstance(presets, dict) else {}
        except Exception as exc:  # noqa: BLE001 - a missing list costs the select, not a render
            logger.warning("Could not list BuzzEdit's audio rack presets (%s).", exc)
            return None

    def apply_rack_preset(self, project_id: str, scope: str, name: str) -> Optional[Dict[str, Any]]:
        """`POST /api/audio/{project}/rack/apply_preset {scope, name}`: that rack
        ("A1", "MASTER", ...) of the BuzzEdit project becomes the preset's
        effects. Returns `{scope, effects, revision}`, or None when BuzzEdit
        did not take it (not running, an older BuzzEdit, no such preset)."""
        try:
            resp = self._post(f"/api/audio/{project_id}/rack/apply_preset",
                              {"scope": scope, "name": name}, timeout=(5, 30))
            if resp.status_code >= 400:
                try:
                    detail = resp.json().get("detail")
                except ValueError:
                    detail = resp.text[:300]
                raise RuntimeError(f"HTTP {resp.status_code}: {detail or resp.reason}")
            return resp.json()
        except Exception as exc:  # noqa: BLE001 - the render keeps the rack it had
            logger.warning("Could not apply the audio rack preset %r to %s of BuzzEdit project %s (%s).",
                           name, scope, project_id, exc)
            return None

    # -------------------------------------------------------- voice conversion
    #
    # BuzzEdit's voice conversion (its routes/audio_voice.py, VOICE_CHANGER_PLAN.md
    # brief S3): the voices library and presets, a project's speaker spans and
    # voice map, and the job that converts every mapped speaker's lines before
    # the render. Best-effort, like the rack presets: a failure is logged and
    # answered with None, and the render keeps the creator's own voice.

    def _voice_call(self, method: str, path: str, what: str, body: Optional[Dict[str, Any]] = None,
                    timeout: Tuple[int, int] = (5, 30)) -> Optional[Dict[str, Any]]:
        try:
            if body is None:
                resp = self._send(method, path, timeout)
            else:
                resp = self._send(method, path, timeout, json=body)
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}: {_detail(resp) or resp.reason}")
            data = resp.json()
            return data if isinstance(data, dict) else {}
        except Exception as exc:  # noqa: BLE001 - a voice step never fails a render
            logger.warning("Could not %s (%s).", what, exc)
            return None

    def list_voices(self) -> Optional[list]:
        """`GET /api/audio/voices` -> the voices library
        `[{name, kind, consent, created, seconds, source, path}]`, or None when
        BuzzEdit did not answer (an older BuzzEdit has no such route)."""
        data = self._voice_call("GET", "/api/audio/voices", "list BuzzEdit's voices library", timeout=(5, 15))
        if data is None:
            return None
        voices = data.get("voices")
        return [v for v in voices if isinstance(v, dict)] if isinstance(voices, list) else []

    def voice_presets(self) -> Optional[Dict[str, Any]]:
        """`GET /api/audio/voice/presets` -> `{engine_defaults, presets: {name:
        {name, voice, voice_in_library, engine, fx, fx_rack, params}}}`, or None."""
        return self._voice_call("GET", "/api/audio/voice/presets", "read BuzzEdit's voice presets", timeout=(5, 15))

    def speaker_spans(self, project_id: str) -> Optional[Dict[str, Any]]:
        """`GET /api/audio/{project}/speaker_spans` -> `{has_script, spans:
        [{speaker, start_s, end_s, text}], speakers}`: who speaks when, from the
        project's script labels and kept words. None when BuzzEdit did not answer."""
        return self._voice_call("GET", f"/api/audio/{project_id}/speaker_spans",
                                f"read the speaker spans of BuzzEdit project {project_id}")

    def put_voice_map(self, project_id: str, voice_map: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """`PUT /api/audio/{project}/voice_map {voice_map}`: {speaker -> {voice,
        preset?, match_pitch, pitch_shift, steps}}. Returns `{voice_map}` as
        BuzzEdit stored it, or None when it refused (an unknown voice, the
        narrator) or did not answer."""
        return self._voice_call("PUT", f"/api/audio/{project_id}/voice_map",
                                f"set the voice map of BuzzEdit project {project_id}",
                                body={"voice_map": voice_map})

    def apply_voice_map(self, project_id: str) -> Optional[str]:
        """`POST /api/audio/{project}/voice/apply_map`: start converting every
        span of every mapped speaker into one new version of the source. The
        job id to follow with `wait_job`, or None when it did not start
        (no seed-vc, a render running, no script)."""
        data = self._voice_call("POST", f"/api/audio/{project_id}/voice/apply_map",
                                f"start the voice conversion of BuzzEdit project {project_id}", body={})
        job_id = (data or {}).get("job_id")
        return str(job_id) if job_id else None

    def stop_voice_worker(self) -> Optional[Dict[str, Any]]:
        """`POST /api/audio/voice/worker/stop`: the seed-vc worker quits and
        frees its VRAM (~3 GB) before the render. `{running, device, idle_s}`."""
        return self._voice_call("POST", "/api/audio/voice/worker/stop", "stop BuzzEdit's voice worker",
                                body={}, timeout=(5, 120))

    def wait_job(self, project_id: str, job_id: str, timeout_s: Optional[float] = None,
                 progress_cb: Optional[Callable[[float, str], None]] = None,
                 poll_seconds: float = 5.0,
                 stall_seconds: float = AUDIO_JOB_STALL_SECONDS) -> Optional[Dict[str, Any]]:
        """Follow a BuzzEdit audio job (`GET /api/audio/{project}/process/{job_id}`)
        until it is completed or failed, and return its record (`{status,
        progress, message, result, error}`).

        Like a transcription, the work has no fixed ceiling (`timeout_s` None):
        the wait ends -- with None, logged -- only when the job's progress and
        message have not changed for `stall_seconds`, BuzzEdit has not answered
        for `UNREACHABLE_GRACE_SECONDS`, BuzzEdit no longer knows the job (404:
        restarted), or a `timeout_s` given runs out. Never raises."""
        path = f"/api/audio/{project_id}/process/{job_id}"
        started = time.monotonic()
        last_seen: Optional[Tuple[float, str]] = None
        last_change = started
        last_logged = 0.0
        unreachable_since: Optional[float] = None
        while True:
            job: Any = None
            try:
                resp = self._get(path, timeout=(5, 30))
                if resp.status_code == 404:
                    logger.warning("BuzzEdit no longer knows audio job %s of %s (restarted?).", job_id, project_id)
                    return None
                if resp.status_code >= 400:
                    raise BuzzEditUnavailable(f"HTTP {resp.status_code}: {_detail(resp) or resp.reason}")
                job = resp.json()
                unreachable_since = None
            except Exception as exc:  # noqa: BLE001 - one bad poll must not end the wait
                now = time.monotonic()
                unreachable_since = unreachable_since or now
                if now - unreachable_since > UNREACHABLE_GRACE_SECONDS:
                    logger.warning("BuzzEdit stopped answering about audio job %s (%s).", job_id, exc)
                    return None
                logger.warning("Audio job poll for %s failed (%s); trying again.", job_id, exc)
                time.sleep(poll_seconds)
                continue
            now = time.monotonic()
            if isinstance(job, dict):
                status = str(job.get("status") or "")
                if status in ("completed", "failed"):
                    logger.info("BuzzEdit audio job %s %s after %ds%s.", job_id, status, int(now - started),
                                f": {job.get('error')}" if job.get("error") else "")
                    return job
                try:
                    progress = float(job.get("progress") or 0.0)
                except (TypeError, ValueError):
                    progress = 0.0
                message = str(job.get("message") or "")
                if (progress, message) != last_seen:
                    last_seen, last_change = (progress, message), now
                    if progress_cb:
                        try:
                            progress_cb(progress, message)
                        except Exception:  # noqa: BLE001 - status text must never end the wait
                            pass
                    if now - last_logged >= 30:
                        last_logged = now
                        logger.info("BuzzEdit audio job %s: %d%% %s", job_id, round(progress * 100), message)
            if now - last_change > stall_seconds:
                logger.warning("BuzzEdit audio job %s has shown no progress for %d minutes (at %r); "
                               "not waiting any longer.", job_id, int(stall_seconds // 60),
                               last_seen[1] if last_seen else "")
                return None
            if timeout_s is not None and now - started > timeout_s:
                logger.warning("BuzzEdit audio job %s still running after %ds; not waiting any longer.",
                               job_id, int(now - started))
                return None
            time.sleep(poll_seconds)

    # ---------------------------------------------------------- live settings

    def set_live_settings(self, project_id: str, overrides: Dict[str, Any]) -> Dict[str, Any]:
        """`PUT /api/presentation/{id}/live_settings`: the mix (coverage, clip
        and still shares, cutaway seconds) a presentation pass that is
        ALREADY RUNNING switches to -- it re-reads them before every clip and
        before placement. Also written before every new pass so the file
        always mirrors the latest intent. Raises on an older BuzzEdit (404)."""
        resp = self._put(f"/api/presentation/{project_id}/live_settings", overrides, timeout=(5, 15))
        resp.raise_for_status()
        return resp.json()

    def get_live_settings(self, project_id: str) -> Dict[str, Any]:
        resp = self._get(f"/api/presentation/{project_id}/live_settings", timeout=(5, 15))
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        return resp.json().get("live_settings") or {}

    def clear_vram(self) -> Dict[str, Any]:
        """`POST /api/system/clear_vram`: BuzzEdit drops its Whisper/aligner
        weights and asks an idle ComfyUI to unload its models."""
        resp = self._post("/api/system/clear_vram", {}, timeout=(5, 60))
        resp.raise_for_status()
        return resp.json()

    def set_app_settings(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """`PUT /api/settings/`: merge `updates` into BuzzEdit's app settings."""
        resp = self._put("/api/settings/", updates, timeout=(5, 15))
        resp.raise_for_status()
        return resp.json()

    # ----------------------------------------------------------- scheduler

    def enqueue_presentation(self, project_id: str, settings: Dict[str, Any], start_at: str = "") -> Dict[str, Any]:
        """`POST /api/scheduler/enqueue` with `job_type="presentation"`.

        `settings` is passed through to BuzzEdit's `PresentationSettings(**settings)`
        as-is -- use real field names (see `integrations/buzzedit_settings.py`).
        Studio renders jump BuzzEdit's queue (`STUDIO_JOB_PRIORITY`).
        """
        body = {"project_id": project_id, "job_type": "presentation", "settings": settings, "start_at": start_at,
                "priority": STUDIO_JOB_PRIORITY}
        resp = self._post("/api/scheduler/enqueue", body, timeout=(5, 30))
        resp.raise_for_status()
        return resp.json()

    def enqueue_rerender(self, project_id: str) -> Dict[str, Any]:
        """`POST /api/scheduler/enqueue` with `job_type="presentation_render"`:
        render the timeline a presentation pass already saved, skipping every
        stage before the render. For the retry after a render that died."""
        body = {"project_id": project_id, "job_type": "presentation_render", "settings": {},
                "priority": STUDIO_JOB_PRIORITY}
        resp = self._post("/api/scheduler/enqueue", body, timeout=(5, 30))
        resp.raise_for_status()
        return resp.json()

    def get_jobs(self) -> Dict[str, Any]:
        """`GET /api/scheduler/jobs` -> `{is_running, is_paused, current_job_id, jobs: [...]}`."""
        resp = self._get("/api/scheduler/jobs", timeout=(5, 15))
        resp.raise_for_status()
        return resp.json()

    def cancel_job(self, job_id: str) -> bool:
        """`DELETE /api/scheduler/jobs/{id}`. Stops a job still pending in
        BuzzEdit's queue; a job already running only gets marked cancelled --
        BuzzEdit's scheduler cannot abort one mid-render. False on a 404."""
        resp = self._send("DELETE", f"/api/scheduler/jobs/{job_id}", (5, 15))
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        return True

    # --------------------------------------------------------- presentation

    def start_effects_sample(self, project_id: str, settings: Dict[str, Any],
                             seconds: float = 20.0) -> Dict[str, Any]:
        """`POST /api/presentation/{id}/effects_sample` -- ~20 s of the cut with
        the effects placed on purpose, rendered small (BuzzEdit
        presentation/effects_sample.py). Returns the job status."""
        resp = self._post(f"/api/presentation/{project_id}/effects_sample",
                          {"settings": settings, "seconds": seconds}, timeout=(5, 30))
        resp.raise_for_status()
        return resp.json()

    def get_effects_sample(self, project_id: str) -> Dict[str, Any]:
        """`GET /api/presentation/{id}/effects_sample` -> {status, progress, message, result}."""
        resp = self._get(f"/api/presentation/{project_id}/effects_sample", timeout=(5, 15))
        resp.raise_for_status()
        return resp.json()


    # ----------------------------------------------------------- motion gallery
    #
    # The Motion Gallery (docs/MOTION_GRAPHICS_PLAN.md M11): every registered
    # motion composition rendered with sample props into a dated, browsable
    # folder (BuzzEdit's routes/motion_gallery.py).

    def start_motion_gallery(self, themes: Optional[List[str]] = None,
                             width: Optional[int] = None, height: Optional[int] = None) -> Dict[str, Any]:
        """`POST /api/motion/gallery`. Raises `RuntimeError` with BuzzEdit's
        own detail on a non-2xx answer (409 while a production render is
        running, 503 if the motion engine cannot be listed)."""
        body: Dict[str, Any] = {}
        if themes:
            body["themes"] = themes
        if width:
            body["width"] = int(width)
        if height:
            body["height"] = int(height)
        resp = self._post("/api/motion/gallery", body, timeout=(5, 30))
        if resp.status_code >= 400:
            raise RuntimeError(f"BuzzEdit could not start the motion gallery: {_detail(resp) or resp.status_code}")
        return resp.json()

    def motion_gallery_status(self) -> Dict[str, Any]:
        """`GET /api/motion/gallery` -> `{state, folder, count, errors, ...}`."""
        resp = self._get("/api/motion/gallery", timeout=(5, 15))
        resp.raise_for_status()
        return resp.json()

    def get_report(self, project_id: str) -> Optional[Dict[str, Any]]:
        """`GET /api/presentation/{id}/report`, None on a 404 (no render yet)."""
        resp = self._get(f"/api/presentation/{project_id}/report")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def get_shot_plan(self, project_id: str) -> Optional[Dict[str, Any]]:
        """`GET /api/presentation/{id}/shot_plan`, None on a 404 (no B-roll pass yet)."""
        resp = self._get(f"/api/presentation/{project_id}/shot_plan")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    # --------------------------------------------------------------- vibe reels
    #
    # BuzzEdit's recording-less vibe-reel renderer (REELS_DESK_PLAN.md §6, VR1):
    # a plain portrait render from a shot list and couplet cards, no take, no
    # presentation planner. `vibe_reel` starts the job; `vibe_reel_job` follows
    # it -- `auto_story.make_mood_reel` polls it with no fixed ceiling, the way
    # a narration job is followed.

    def vibe_reel(self, body: Dict[str, Any], wait_s: float = 5400.0) -> Dict[str, Any]:
        """`POST /api/reels/vibe` -> `{job_id}`. BuzzEdit renders one reel at a time and
        answers 409 while another is rendering: wait for it (up to `wait_s`) instead of
        failing the reel (2026-10-23: the storm reel arrived while moonlight still ran)."""
        deadline = time.monotonic() + wait_s
        resp = self._post("/api/reels/vibe", body, timeout=(10, 60))
        while resp.status_code == 409 and time.monotonic() < deadline:
            time.sleep(30)
            resp = self._post("/api/reels/vibe", body, timeout=(10, 60))
        if resp.status_code >= 400:
            raise RuntimeError(f"BuzzEdit could not start the vibe reel: {_detail(resp) or resp.status_code}")
        return resp.json()

    def vibe_reel_busy(self) -> bool:
        """`GET /api/reels/busy`: whether BuzzEdit is rendering a reel. A slow answer counts
        as busy: BuzzEdit answers late exactly when ComfyUI owns the GPU, and reading a
        timeout as "free" let an LLM load mid-clip (Fable review, 2026-10-24). A refused
        connection (BuzzEdit not running) or an old BuzzEdit without the route is free."""
        import requests as _rq
        try:
            resp = self._get("/api/reels/busy", timeout=(5, 30))
            return resp.status_code == 200 and bool(resp.json().get("busy"))
        except _rq.exceptions.Timeout:
            return True
        except Exception:  # noqa: BLE001 - not running / no route: nothing of its to protect
            return False

    def vibe_reel_job(self, job_id: str) -> Dict[str, Any]:
        """`GET /api/reels/jobs/{id}` -> `{state, progress, message, result, error}`."""
        resp = self._get(f"/api/reels/jobs/{job_id}", timeout=(5, 30))
        if resp.status_code >= 400:
            raise RuntimeError(f"BuzzEdit vibe reel job {job_id}: {resp.status_code} {resp.text[:300]}")
        return resp.json()

    def narration_busy(self) -> bool:
        """`GET /api/narration/busy`: whether BuzzEdit is synthesising narration right
        now -- same shape and the same "unsure/slow means busy" rule as `vibe_reel_busy`
        (STUDIO_DIRECTOR_PLAN.md enhancement 2/5): a narration holds the GPU just as a
        reel render does. A refused connection or an old BuzzEdit without the route is free."""
        import requests as _rq
        try:
            resp = self._get("/api/narration/busy", timeout=(5, 30))
            return resp.status_code == 200 and bool(resp.json().get("busy"))
        except _rq.exceptions.Timeout:
            return True
        except Exception:  # noqa: BLE001 - not running / no route: nothing of its to protect
            return False

    # ------------------------------------------------------- supervisor (watchdog)

    def set_supervisor_parent(self, pid: int) -> Optional[Dict[str, Any]]:
        """`POST /api/supervisor/parent {pid}` (STUDIO_DIRECTOR_PLAN.md enhancement 4):
        tell a headless BuzzEdit we adopted (it was already running on its port, so we
        did not spawn it) to watch *our* pid instead of the one that started it. None
        when BuzzEdit did not answer (an older BuzzEdit without the route) -- the
        Electron watchdog then keeps following its original parent."""
        try:
            resp = self._post("/api/supervisor/parent", {"pid": int(pid)}, timeout=(5, 15))
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001 - best effort, like the master pause mirror
            logger.info("BuzzEdit supervisor re-parent not applied (%s).", exc)
            return None

    # -------------------------------------------------------- master pause
    #
    # The master pause/resume (docs/STUDIO_DIRECTOR_PLAN.md Part 1): BuzzEdit
    # mirrors the Studio's own `/api/master/*` so one switch holds both apps.

    def master_pause(self, mode: str = "soft", reason: str = "", by: str = "") -> Optional[Dict[str, Any]]:
        """`POST /api/master/pause {mode, reason, by}`. None when BuzzEdit did
        not answer -- the Studio's own pause still applies."""
        try:
            resp = self._post("/api/master/pause", {"mode": mode, "reason": reason, "by": by}, timeout=(5, 30))
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001 - BuzzEdit down is not a reason to fail the pause
            logger.info("BuzzEdit master pause not applied (%s).", exc)
            return None

    def master_resume(self) -> Optional[Dict[str, Any]]:
        """`POST /api/master/resume`. None when BuzzEdit did not answer."""
        try:
            resp = self._post("/api/master/resume", {}, timeout=(5, 30))
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.info("BuzzEdit master resume not applied (%s).", exc)
            return None

    def master_state(self) -> Optional[Dict[str, Any]]:
        """`GET /api/master/state`, or None when BuzzEdit did not answer."""
        try:
            resp = self._get("/api/master/state", timeout=(5, 15))
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.debug("BuzzEdit master state read failed (%s).", exc)
            return None

    # ------------------------------------------------------------ sfx library
    #
    # BuzzEdit's real-sound-effects library and generator (its routes/sfx.py,
    # CLIPS_AND_SOUND_PLAN.md brief S3): folders of effects/beds it indexes,
    # and a ComfyUI-backed generator for one the library does not have.
    # Best-effort like the voice calls: None on any failure, logged.

    def get_sfx_library(self) -> Optional[Dict[str, Any]]:
        """`GET /api/sfx/library` -> `{dirs, default, roots, count, effects,
        beds, music, tags, missing, indexed_at}`, or None on any failure."""
        return self._voice_call("GET", "/api/sfx/library", "read BuzzEdit's SFX library", timeout=(5, 15))

    def set_sfx_library(self, dirs: List[str]) -> Optional[Dict[str, Any]]:
        """`PUT /api/sfx/library {dirs}`. On an older BuzzEdit without the
        dedicated route (`_voice_call` returns None for that the same as any
        other failure), falls back to `set_app_settings({"sfx_library_dirs":
        dirs})` so the folders are saved somewhere rather than lost; returns
        `{"dirs": dirs, "fallback": True}` for that path, or None if the
        fallback failed too."""
        data = self._voice_call("PUT", "/api/sfx/library", "set BuzzEdit's SFX library folders",
                                body={"dirs": dirs})
        if data is not None:
            return data
        try:
            self.set_app_settings({"sfx_library_dirs": dirs})
            return {"dirs": dirs, "fallback": True}
        except Exception as exc:  # noqa: BLE001 - no library push at all this time
            logger.warning("Could not set BuzzEdit's SFX library folders (%s).", exc)
            return None

    def refresh_sfx_library(self) -> Optional[Dict[str, Any]]:
        """`POST /api/sfx/library/refresh`: re-scan the saved folders now."""
        return self._voice_call("POST", "/api/sfx/library/refresh", "refresh BuzzEdit's SFX library", body={})

    def generate_sfx(self, text: str, kind: str = "accent", seconds: Optional[float] = None) -> Dict[str, Any]:
        """`POST /api/sfx/generate {text, kind, seconds}`: ask BuzzEdit's
        ComfyUI-backed pipeline for an effect the library does not have.

        Raises `RuntimeError` with BuzzEdit's own detail on an HTTP 503
        (ComfyUI offline) or 409 (busy) -- unlike the other SFX calls, this one
        goes through `_send` directly rather than `_voice_call`, so the status
        reaches the caller instead of collapsing into a bare None."""
        body: Dict[str, Any] = {"text": text, "kind": kind}
        if seconds is not None:
            body["seconds"] = seconds
        resp = self._send("POST", "/api/sfx/generate", (5, 30), json=body)
        if resp.status_code in (503, 409):
            raise RuntimeError(f"HTTP {resp.status_code}: {_detail(resp) or resp.reason}")
        resp.raise_for_status()
        return resp.json()

    def sfx_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """`GET /api/sfx/jobs/{id}` -> `{job_id, state, stage, text, kind,
        seconds, path, duration_s, error}`, or None on any failure."""
        return self._voice_call("GET", f"/api/sfx/jobs/{job_id}", f"read BuzzEdit SFX job {job_id}",
                                timeout=(5, 15))

    def sfx_file(self, path: str) -> requests.Response:
        """`GET /api/sfx/file?path=...`, streamed: the raw audio bytes of one
        library or generated effect, for a route to pass straight through."""
        from urllib.parse import quote

        base = self._base()
        return requests.get(f"{base}/api/sfx/file?path={quote(path)}", timeout=(5, 60), stream=True)
