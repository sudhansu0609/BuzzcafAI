"""The Motion Gallery proxy (docs/MOTION_GRAPHICS_PLAN.md M11): the Studio
only forwards start/status to BuzzEdit. No real BuzzEdit call is made."""
from fastapi.testclient import TestClient

from app.api import motion_gallery_api
from app.main import app


class FakeBuzzEdit:
    def start_motion_gallery(self, themes=None, width=None, height=None):
        return {"state": "running", "folder": None, "count": 0, "errors": [], "total": 5}

    def motion_gallery_status(self):
        return {"state": "completed", "folder": r"B:\Samples\motion_gallery\2026-10-28",
                "count": 5, "errors": []}


def test_start_and_status_proxy_to_buzzedit(monkeypatch):
    monkeypatch.setattr(motion_gallery_api, "BuzzEditClient", lambda: FakeBuzzEdit())
    client = TestClient(app)

    r = client.post("/api/motion_gallery/start", json={"themes": ["clean"]})
    assert r.status_code == 200
    assert r.json()["total"] == 5

    r = client.get("/api/motion_gallery/status")
    assert r.status_code == 200
    assert r.json()["count"] == 5
