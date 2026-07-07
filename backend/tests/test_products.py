from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_search_products_returns_results() -> None:
    response = client.get("/api/v1/products/search?q=laptop")
    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "laptop"
    assert payload["items"]
    first_item = payload["items"][0]
    assert "name" in first_item
    assert "price" in first_item
