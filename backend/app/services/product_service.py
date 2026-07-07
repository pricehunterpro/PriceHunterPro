from __future__ import annotations

from typing import Any


class ProductService:
    """Servicio simple para devolver datos de ejemplo del catálogo."""

    def search_products(self, query: str, store: str | None = None, category: str | None = None) -> list[dict[str, Any]]:
        normalized_query = query.strip().lower()
        if not normalized_query:
            normalized_query = "producto"

        items = [
            {
                "id": "prod-001",
                "name": f"{normalized_query.title()} Premium",
                "brand": "Marca Demo",
                "price": 129.9,
                "store": store or "falabella",
                "category": category or "general",
                "in_stock": True,
            },
            {
                "id": "prod-002",
                "name": f"{normalized_query.title()} Básico",
                "brand": "Marca Demo",
                "price": 89.9,
                "store": store or "ripley",
                "category": category or "general",
                "in_stock": True,
            },
        ]
        return items
