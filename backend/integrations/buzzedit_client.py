"""
Talk to BuzzEdit, the ComfyUI-backed auto-editor that turns a recording plus
an annotated script into a rendered video.

BuzzcafAI and BuzzEdit are sibling desktop apps that both prefer port 8099 --
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
from typing import Any, Dict, Optional, Tuple

import requests

logger = logging.getLogger("buzzcaf_ai.buzzedit_client")


class BuzzEditUnavailable(Exception):
    """BuzzEdit could not be found, or did not answer."""


def base_url() -> Optional[str]:
    """Where BuzzEdit is listening, or None. Ledger discovery, not a guess.

    `BUZZEDIT_URL` (env, or the `buzzedit_url` config key) is an explicit
    override for an unusual setup; the normal path is the shared port ledger
    both apps publish to (`buzzcaf_ports.discover`), which resolves the 8099
    collision between the two backends by checking who a listener actually
    says it is, rather than trusting whichever process got there first.
    """
    from integrations import buzzcaf_ports
    from core.config import config_manager

    env_url = os.environ.get("BUZZEDIT_URL") or config_manager.get("BUZZEDIT_URL")
    return buzzcaf_ports.discover("buzzedit", 8099, health_path="/api/health", env_url=env_url)


class BuzzEditClient:
    """One method per BuzzEdit endpoint `produce_video` needs.

    Re-resolves `base_url()` on every call rather than caching it on the
    instance: `buzzcaf_ports.discover` already caches for 3s internally, so
    this stays cheap while still noticing BuzzEdit restarting on a new port
    mid-run.
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

    def _get(self, path: str, timeout: Optional[Tuple[int, int]] = None) -> requests.Response:
        try:
            return requests.get(f"{self._base()}{path}", timeout=timeout or self.timeout)
        except requests.RequestException as exc:
            raise BuzzEditUnavailable(f"BuzzEdit did not answer GET {path}: {exc}") from exc

    def _post(
        self, path: str, json_body: Optional[Dict[str, Any]] = None, timeout: Optional[Tuple[int, int]] = None
    ) -> requests.Response:
        try:
            return requests.post(f"{self._base()}{path}", json=json_body or {}, timeout=timeout or self.timeout)
        except requests.RequestException as exc:
            raise BuzzEditUnavailable(f"BuzzEdit did not answer POST {path}: {exc}") from exc

    def _put(
        self, path: str, json_body: Optional[Dict[str, Any]] = None, timeout: Optional[Tuple[int, int]] = None
    ) -> requests.Response:
        try:
            return requests.put(f"{self._base()}{path}", json=json_body or {}, timeout=timeout or self.timeout)
        except requests.RequestException as exc:
            raise BuzzEditUnavailable(f"BuzzEdit did not answer PUT {path}: {exc}") from exc

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
        resp = self._post("/api/projects/import_path", {"path": path}, timeout=(5, 120))
        resp.raise_for_status()
        return resp.json()

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        resp = self._get(f"/api/projects/{project_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------- transcription

    def transcribe(self, project_id: str, language: Optional[str] = None) -> Dict[str, Any]:
        """`POST /api/transcription/transcribe`.

        This blocks on BuzzEdit's side until Whisper transcription and
        auto-edit planning finish -- minutes for a long recording, hence the
        generous read timeout. It is not the scheduler's job system; the
        response is the final result, not a job id to poll.
        """
        body: Dict[str, Any] = {"project_id": project_id}
        if language is not None:
            body["language"] = language
        resp = self._post("/api/transcription/transcribe", body, timeout=(10, 1800))
        resp.raise_for_status()
        return resp.json()

    # -------------------------------------------------------------- script

    def set_script(self, project_id: str, text: str) -> Dict[str, Any]:
        """`PUT /api/projects/{id}/script`. Aligns to the transcript if one
        exists yet, else stores the text un-aligned."""
        resp = self._put(f"/api/projects/{project_id}/script", {"text": text}, timeout=(5, 60))
        resp.raise_for_status()
        return resp.json()

    def get_script(self, project_id: str) -> Dict[str, Any]:
        """`GET /api/projects/{id}/script`.

        Note: the response's `paragraphs` field is an integer count, not a
        list of paragraph objects -- do not index it.
        """
        resp = self._get(f"/api/projects/{project_id}/script")
        resp.raise_for_status()
        return resp.json()

    # ----------------------------------------------------------- scheduler

    def enqueue_presentation(self, project_id: str, settings: Dict[str, Any], start_at: str = "") -> Dict[str, Any]:
        """`POST /api/scheduler/enqueue` with `job_type="presentation"`.

        `settings` is passed through to BuzzEdit's `PresentationSettings(**settings)`
        as-is -- use real field names (see `integrations/buzzedit_settings.py`).
        """
        body = {"project_id": project_id, "job_type": "presentation", "settings": settings, "start_at": start_at}
        resp = self._post("/api/scheduler/enqueue", body, timeout=(5, 30))
        resp.raise_for_status()
        return resp.json()

    def get_jobs(self) -> Dict[str, Any]:
        """`GET /api/scheduler/jobs` -> `{is_running, is_paused, current_job_id, jobs: [...]}`."""
        resp = self._get("/api/scheduler/jobs", timeout=(5, 15))
        resp.raise_for_status()
        return resp.json()

    # --------------------------------------------------------- presentation

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
