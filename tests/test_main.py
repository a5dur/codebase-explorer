import pytest
from fastapi.testclient import TestClient


def test_health_lmstudio_down():
    """Health returns lmstudio: false when LM Studio not reachable."""
    from main import app
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "lmstudio" in data
    assert isinstance(data["lmstudio"], bool)
