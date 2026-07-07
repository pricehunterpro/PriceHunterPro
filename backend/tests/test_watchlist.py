from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_watchlist_endpoint() -> None:
    response = client.get("/api/v1/watchlist")
    assert response.status_code == 200
    payload = response.json()
    assert "items" in payload
