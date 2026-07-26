from fastapi.testclient import TestClient
from apps.api.main import app

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_projects_endpoint():
    response = client.get("/projects")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
