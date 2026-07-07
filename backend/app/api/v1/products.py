from fastapi import APIRouter, Query

from app.services.product_service import ProductService

router = APIRouter(prefix="/products", tags=["products"])
product_service = ProductService()


@router.get("/search")
def search_products(q: str = Query(default=""), store: str | None = None, category: str | None = None) -> dict[str, object]:
    items = product_service.search_products(query=q, store=store, category=category)
    return {"query": q, "store": store, "category": category, "items": items}


@router.get("/{product_id}")
def get_product(product_id: str) -> dict[str, str]:
    return {"id": product_id, "message": "Detalle del producto disponible próximamente"}


@router.get("/{product_id}/price-history")
def get_price_history(product_id: str, days: int = 30) -> dict[str, object]:
    return {"product_id": product_id, "days": days, "history": []}
