from fastapi import APIRouter, Query

from app.services.deal_service import DealService

router = APIRouter(prefix="/deals", tags=["deals"])
deal_service = DealService()


@router.get("")
def get_deals(
    store: str | None = Query(default=None),
    category: str | None = Query(default=None),
    brand: str | None = Query(default=None),
    sort: str = Query(default="discount"),
    q: str = Query(default=""),
    min_discount: int = Query(default=0),
    min_price: float = Query(default=0.0),
    page: int = Query(default=1),
    limit: int = Query(default=50),
    below_market: bool = Query(default=False),
) -> dict[str, object]:
    stores = [value for value in (store or "").split(",") if value] or None
    categories = [value for value in (category or "").split(",") if value] or None
    brands = [value for value in (brand or "").split(",") if value] or None

    return deal_service.get_deals(
        stores=stores,
        categories=categories,
        brands=brands,
        sort=sort,
        q=q,
        min_discount=min_discount,
        min_price=min_price,
        page=page,
        limit=limit,
        below_market=below_market,
    )


@router.get("/stats")
def get_stats() -> dict[str, object]:
    return deal_service.get_stats()


@router.post("/scrape/trigger")
def trigger_scrape() -> dict[str, str]:
    import redis as _redis
    from app.core.config import get_settings
    from app.tasks.celery_app import scrape_all_stores
    try:
        r = _redis.from_url(get_settings().redis_url)
    except Exception:
        r = None
    # Si ya hay un scraping en curso (lock del singleton), no disparamos otro
    # —evita el deadlock— y devolvemos el task real en ejecución para que el
    # front siga mostrando el progreso.
    if r is not None and r.exists("lock:scrape_all_stores"):
        existing = (r.get("scrape_active_task") or b"").decode()
        return {"status": "already_running", "task_id": existing,
                "message": "Ya hay un scraping en curso"}
    task = scrape_all_stores.delay()
    if r is not None:
        try:
            r.set("scrape_active_task", task.id, ex=1800)
        except Exception:
            pass
    return {"status": "accepted", "task_id": task.id, "message": "Scraping started"}


@router.get("/scrape/status")
def scrape_status() -> dict[str, object]:
    import redis as _redis
    from celery.result import AsyncResult
    from app.core.config import get_settings
    try:
        r = _redis.from_url(get_settings().redis_url)
        task_id = (r.get("scrape_active_task") or b"").decode()
        if not task_id:
            return {"running": False, "task_id": None}
        result = AsyncResult(task_id)
        running = result.state in ("PENDING", "STARTED", "RETRY")
        if not running:
            r.delete("scrape_active_task")
        return {"running": running, "task_id": task_id, "state": result.state}
    except Exception:
        return {"running": False, "task_id": None}


@router.post("/telegram/publish")
def trigger_telegram_publish(
    limit: int = Query(default=5, ge=1, le=20),
    min_discount: float = Query(default=40.0, ge=0, le=99),
) -> dict[str, object]:
    """Publica manualmente los mejores deals en el canal de Telegram."""
    from app.tasks.celery_app import publish_top_deals
    task = publish_top_deals.delay(limit=limit, min_discount=min_discount)
    return {"status": "accepted", "task_id": task.id, "message": f"Publicando top {limit} deals (>= {min_discount}% descuento)"}


@router.post("/tiktok/generate")
def trigger_tiktok_image(
    min_discount: float = Query(default=35.0, ge=0, le=99),
) -> dict[str, object]:
    """Genera imagen TikTok del mejor deal y la envía al admin por Telegram."""
    from app.tasks.celery_app import generate_tiktok_content
    task = generate_tiktok_content.delay(min_discount=min_discount)
    return {"status": "accepted", "task_id": task.id, "message": f"Generando imagen TikTok (>= {min_discount}% descuento)"}
