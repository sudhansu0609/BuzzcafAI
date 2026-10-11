"""
Studio -> BuzzAnimate (BuzzAnimate docs/ECOSYSTEM_BRIDGE_PLAN.md step E5):
`app/api/buzzanimate_api.py` against a *fake* BuzzAnimate -- a tiny threaded
`http.server` on an ephemeral port speaking BuzzAnimate's API shape
(`crates/buzz-app/src/api.rs`), found through a temp port ledger
(`BUZZCAF_PORTS_FILE`). The BuzzEdit hand-off goes through the real
`BuzzEditClient`, pinned to a fake BuzzEdit. No real app is started.
"""

import json
import os
import shutil
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app.api import buzzanimate_api
from app.main import app
from app.services import events
from core.models.project import Project
from integrations import buzzanimate_client as animate
from integrations import buzzcaf_ports
from integrations import buzzedit_client


class FakeServer:
    """A JSON server whose answers come from `route(method, path, body)`."""

    def __init__(self, route):
        self.requests = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _serve(self, body):
                fake.requests.append({"method": self.command, "path": self.path, "body": body,
                                      "origin": self.headers.get("Origin")})
                status, answer = route(self.command, self.path, body)
                data = json.dumps(answer).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._serve(None)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                self._serve(json.loads(self.rfile.read(length) or b"{}"))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class FakeBuzzAnimate(FakeServer):
    def __init__(self, fail_episode=None):
        self.jobs = {}
        self.fail_episode = fail_episode
        super().__init__(self.route)

    def _job(self, kind, output, result=None, error=None):
        job_id = len(self.jobs) + 1
        self.jobs[job_id] = {"id": job_id, "kind": kind, "state": "running", "progress": None,
                             "output": output, "error": error, "result": result, "polls": 0}
        return job_id

    def route(self, method, path, body):
        if path == "/health":
            return 200, {"app": "buzzanimate", "status": "ok", "port": self.port, "pid": 1, "version": "test"}
        if path == "/api/state":
            return 200, {"path": None}
        if path == "/api/call" and method == "POST":
            return 200, {"ok": True, "value": {"tool": body["tool"]}, "error": None}
        if path == "/api/episode" and method == "POST":
            if not os.path.isfile(body.get("script_path") or ""):
                return 400, {"ok": False, "error": "no script"}
            out = body["out_dir"]
            buzz = os.path.join(out, "draft.buzz")
            with open(buzz, "w") as f:
                f.write("{}")
            renders = []
            if body.get("render"):
                os.makedirs(os.path.join(out, "previews"), exist_ok=True)
                for n in (1, 2):
                    mp4 = os.path.join(out, "previews", f"scene_{n:02}.mp4")
                    with open(mp4, "wb") as f:
                        f.write(b"mp4")
                    renders.append(self._job("export", mp4))
            result = {"files": [buzz, os.path.join(out, "draft_report.md")], "render_jobs": renders, "warnings": []}
            job_id = self._job("episode", out, result, self.fail_episode)
            return 200, {"ok": True, "job_id": job_id}
        if path.startswith("/api/jobs/"):
            job = self.jobs[int(path.rsplit("/", 1)[1])]
            job["polls"] += 1
            if job["polls"] >= 2:
                job["state"] = "failed" if job["error"] else "done"
            return 200, {k: v for k, v in job.items() if k != "polls"}
        return 404, {"ok": False, "error": f"no route {path}"}


class FakeBuzzEdit(FakeServer):
    def __init__(self):
        super().__init__(self.route)

    def route(self, method, path, body):
        if path == "/api/projects/import_path":
            return 200, {"id": "be_anim_1", "name": os.path.basename(body["path"])}
        if path == "/api/projects/be_anim_1/media/import":
            return 200, {"status": "success", "added": body["paths"]}
        return 404, {"detail": "no route"}


def _dead_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("BUZZCAF_PORTS_FILE", str(tmp_path / "ports.json"))
    monkeypatch.delenv("BUZZANIMATE_URL", raising=False)
    monkeypatch.setattr(animate, "PREFERRED_PORT", _dead_port())
    buzzcaf_ports._forget()
    yield
    buzzcaf_ports._forget()


@pytest.fixture
def fake(ledger):
    server = FakeBuzzAnimate()
    buzzcaf_ports.publish("buzzanimate", server.port, f"{server.url}/health")
    yield server
    server.close()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def events_seen(monkeypatch):
    seen = []
    monkeypatch.setattr(events.bus, "publish", lambda kind, payload=None: seen.append((kind, payload)))
    return seen


@pytest.fixture
def project():
    p = Project(id="animate_test_proj", name="Animate Test", brand="Life3Baje", workflow_name="life3baje_video")
    script_dir = os.path.join(p.get_project_dir(), "script")
    os.makedirs(script_dir, exist_ok=True)
    with open(os.path.join(script_dir, "draft.md"), "w", encoding="utf-8") as f:
        f.write("## [SCENE 01: Hello]\n\n**V.O. (Narrator):** Hello there.\n")
    p.assets["script"] = "script/draft.md"
    p.save()
    yield p
    shutil.rmtree(p.get_project_dir(), ignore_errors=True)
    with buzzanimate_api._animate_lock:
        buzzanimate_api._animate_status.pop(p.id, None)


def _wait(client, project_id, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get(f"/api/projects/{project_id}/animate/status").json()
        if status.get("state") not in ("starting", "running"):
            return status
        time.sleep(0.2)
    raise AssertionError("the animate run is still going")


def test_not_running_is_a_clear_503_that_offers_start(client, ledger, project):
    status = client.get("/api/buzzanimate/status").json()
    assert status["running"] is False and "start: true" in status["message"]
    res = client.post("/api/buzzanimate/call", json={"tool": "new_layer"})
    assert res.status_code == 503 and "start: true" in res.json()["detail"]
    res = client.post(f"/api/projects/{project.id}/animate", json={})
    assert res.status_code == 503


def test_status_and_call_reach_buzzanimate_through_the_ledger(client, fake):
    status = client.get("/api/buzzanimate/status").json()
    assert status["running"] is True and status["url"] == fake.url
    res = client.post("/api/buzzanimate/call", json={"tool": "new_layer", "args": {"name": "Sky"}})
    assert res.status_code == 200, res.text
    assert res.json()["value"] == {"tool": "new_layer"}
    assert all(r["origin"] is None for r in fake.requests)


def test_animate_builds_the_projects_script_into_its_animation_folder(client, fake, project, events_seen):
    res = client.post(f"/api/projects/{project.id}/animate", json={"scenes": [1]})
    assert res.status_code == 200, res.text
    status = _wait(client, project.id)
    assert status["state"] == "ready", status

    out_dir = os.path.join(project.get_project_dir(), "animation")
    episode = next(r for r in fake.requests if r["path"] == "/api/episode")
    assert episode["body"] == {"out_dir": out_dir, "render": False, "scenes": [1],
                               "script_path": os.path.join(project.get_project_dir(), "script/draft.md")}

    stored = Project.load(project.id).metadata["animation_output"]
    assert stored["out_dir"] == out_dir
    assert stored["files"][0].endswith("draft.buzz") and os.path.isfile(stored["files"][0])
    assert stored["videos"] == []

    kinds = [k for k, _ in events_seen]
    assert "animation_progress" in kinds and kinds[-1] == "animation_ready"
    assert events_seen[-1][1]["animation_output"] == stored

    # After a restart the stored result is still the answer.
    with buzzanimate_api._animate_lock:
        buzzanimate_api._animate_status.pop(project.id, None)
    restored = client.get(f"/api/projects/{project.id}/animate/status").json()
    assert restored["state"] == "ready" and restored["animation_output"] == stored


def test_animate_to_buzzedit_renders_and_hands_the_mp4s_over(client, fake, project, events_seen, monkeypatch):
    buzzedit = FakeBuzzEdit()
    monkeypatch.setattr(buzzedit_client, "_sticky_url", buzzedit.url)
    try:
        res = client.post(f"/api/projects/{project.id}/animate", json={"to_buzzedit": True})
        assert res.status_code == 200, res.text
        status = _wait(client, project.id)
        assert status["state"] == "ready", status

        episode = next(r for r in fake.requests if r["path"] == "/api/episode")
        assert episode["body"]["render"] is True  # to_buzzedit needs the MP4s
        stored = Project.load(project.id).metadata["animation_output"]
        assert [os.path.basename(v) for v in stored["videos"]] == ["scene_01.mp4", "scene_02.mp4"]
        assert stored["buzzedit"] == {"buzzedit_project_id": "be_anim_1", "videos": 2}

        posts = [(r["path"], r["body"]) for r in buzzedit.requests]
        assert posts == [
            ("/api/projects/import_path", {"path": stored["videos"][0]}),
            ("/api/projects/be_anim_1/media/import", {"paths": stored["videos"][1:], "copy": True}),
        ]
    finally:
        buzzedit.close()


def test_a_failed_build_is_reported_and_published(client, ledger, project, events_seen):
    server = FakeBuzzAnimate(fail_episode="the script has no scenes in it")
    buzzcaf_ports.publish("buzzanimate", server.port, f"{server.url}/health")
    try:
        assert client.post(f"/api/projects/{project.id}/animate", json={}).status_code == 200
        status = _wait(client, project.id)
        assert status["state"] == "failed" and "no scenes" in status["error"]
        assert events_seen[-1][0] == "animation_failed"
        assert "animation_output" not in Project.load(project.id).metadata
    finally:
        server.close()


def test_animate_checks_its_inputs(client, fake, project):
    assert client.post("/api/projects/no_such_project_x/animate", json={}).status_code == 404
    bare = Project(id="animate_bare_proj", name="Bare", brand="Life3Baje", workflow_name="life3baje_video")
    bare.save()
    try:
        res = client.post(f"/api/projects/{bare.id}/animate", json={})
        assert res.status_code == 400 and "no script" in res.json()["detail"]
    finally:
        shutil.rmtree(bare.get_project_dir(), ignore_errors=True)
    res = client.post(f"/api/projects/{project.id}/animate", json={"casting_path": "Z:/nope/casting.json"})
    assert res.status_code == 404


def test_the_dexter_gateway_lists_the_animate_actions():
    from app.services import dexter_registry
    names = {c["name"] for c in dexter_registry.CAPABILITIES}
    assert {"buzzanimate_status", "buzzanimate_call", "animate_start", "animate_status"} <= names


def test_only_this_machine_may_reach_buzzanimate_through_the_studio(client, fake, project):
    """A web page must not drive BuzzAnimate through the Studio: a foreign
    Origin, or a sandboxed iframe's `null`, is refused before BuzzAnimate is
    asked anything; a backend (no Origin) and a page on this machine are served."""
    for origin in ["https://evil.example", "null", "http://localhost.evil.example"]:
        for method, path, body in [
            ("post", "/api/buzzanimate/call", {"tool": "new_layer"}),
            ("post", f"/api/projects/{project.id}/animate", {}),
        ]:
            res = getattr(client, method)(path, json=body, headers={"Origin": origin})
            assert res.status_code == 403, (origin, path, res.text)
    assert not any(r.get("path") in ("/api/call", "/api/episode") for r in fake.requests), "nothing reached BuzzAnimate"
    for origin in [None, "http://localhost:5173"]:
        headers = {"Origin": origin} if origin else {}
        assert client.get("/api/buzzanimate/status", headers=headers).status_code == 200, origin
