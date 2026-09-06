from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_identifies_the_studio():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok" and body["app"] == "buzzcaf"


def test_projects_endpoint():
    response = client.get("/api/projects")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
