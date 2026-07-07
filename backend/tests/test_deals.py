from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_deals_endpoint_returns_filtered_results() -> None:
    response = client.get("/api/v1/deals?q=nike&store=falabella&sort=discount")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    assert payload["items"]
    assert payload["filters"]["stores"]


def test_deals_stats_endpoint_returns_metrics() -> None:
    response = client.get("/api/v1/deals/stats")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    assert payload["bestDiscount"] >= 0
    assert payload["minPrice"] >= 0
