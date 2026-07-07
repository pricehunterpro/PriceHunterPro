from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/monitoring", tags=["monitoring"])

_STORES = ["falabella", "ripley", "plazavea", "oechsle", "estilos", "sodimac"]

_BEAT_SCHEDULE = [
    {"hour": 0,  "minute": 30},
    {"hour": 1,  "minute": 30},
    {"hour": 3,  "minute": 0},
    {"hour": 6,  "minute": 0},
    {"hour": 8,  "minute": 0},
    {"hour": 10, "minute": 0},
    {"hour": 12, "minute": 0},
    {"hour": 15, "minute": 0},
    {"hour": 18, "minute": 0},
    {"hour": 20, "minute": 0},
    {"hour": 22, "minute": 0},
]


def _get_db():
    from app.core.config import get_settings
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    settings = get_settings()
    engine = create_engine(settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://"))
    return Session(engine)


def _get_redis():
    import redis as _redis
    from app.core.config import get_settings
    return _redis.from_url(get_settings().redis_url)


def _now_lima() -> datetime:
    return datetime.now(timezone.utc)


def _next_run(hour: int, minute: int, now: datetime) -> str:
    from datetime import timedelta
    import pytz
    lima = pytz.timezone("America/Lima")
    now_lima = now.astimezone(lima)
    candidate = now_lima.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now_lima:
        candidate += timedelta(days=1)
    return candidate.strftime("%H:%M")


def _is_scraping(r) -> tuple[bool, str]:
    task_id = (r.get("scrape_active_task") or b"").decode()
    if not task_id:
        return False, ""
    from celery.result import AsyncResult
    state = AsyncResult(task_id).state
    if state in ("PENDING", "STARTED", "RETRY"):
        return True, task_id
    r.delete("scrape_active_task")
    return False, ""


@router.get("/summary")
def get_summary() -> dict[str, Any]:
    from sqlalchemy import text
    r = _get_redis()
    running, _ = _is_scraping(r)

    with _get_db() as session:
        store_rows = session.execute(text("""
            SELECT store,
                   MAX(last_scraped_at) AS last_sync,
                   COUNT(*)        AS total
            FROM store_products
            WHERE last_scraped_at IS NOT NULL
            GROUP BY store
        """)).fetchall()

        products_today = session.execute(text("""
            SELECT COUNT(*) AS cnt FROM store_products
            WHERE last_scraped_at >= NOW() - INTERVAL '24 hours'
        """)).scalar() or 0

    now = _now_lima()
    active = 0
    errors = 0
    last_sync = None

    for row in store_rows:
        if row.last_sync:
            mins_ago = (now - row.last_sync.replace(tzinfo=timezone.utc)).total_seconds() / 60
            if mins_ago < 180:
                active += 1
            elif mins_ago > 1440:
                errors += 1
            if last_sync is None or row.last_sync > last_sync:
                last_sync = row.last_sync

    return {
        "scrapersActivos":     active,
        "scrapersConError":    errors,
        "procesosEjecutando":  1 if running else 0,
        "procesosFallidos":    0,
        "ultimaSincronizacion": last_sync.isoformat() if last_sync else None,
        "productosHoy":        products_today,
        "scrapingActivo":      running,
    }


@router.get("/scrapers")
def get_scrapers() -> list[dict[str, Any]]:
    from sqlalchemy import text
    r = _get_redis()
    running, active_task = _is_scraping(r)
    now = _now_lima()

    with _get_db() as session:
        rows = session.execute(text("""
            SELECT store,
                   MAX(last_scraped_at)       AS last_sync,
                   COUNT(*)              AS total,
                   COUNT(*) FILTER (WHERE in_stock = true) AS in_stock_count
            FROM store_products
            GROUP BY store
        """)).fetchall()

    store_map = {r.store: r for r in rows}
    result = []

    for store in _STORES:
        row = store_map.get(store)
        if row and row.last_sync:
            last_dt = row.last_sync.replace(tzinfo=timezone.utc)
            mins_ago = (now - last_dt).total_seconds() / 60
            if running:
                status = "Ejecutando"
            elif mins_ago < 180:
                status = "Activo"
            elif mins_ago > 1440:
                status = "Error"
            else:
                status = "Finalizado"
            last_sync_str = last_dt.strftime("%d/%m %H:%M")
            mins_int = int(mins_ago)
            duracion = f"{mins_int} min atrás" if mins_int < 60 else f"{mins_int//60}h atrás"
        else:
            status = "Pausado"
            last_sync_str = "—"
            duracion = "—"

        result.append({
            "id":         store,
            "store":      store.capitalize(),
            "status":     status,
            "lastSync":   last_sync_str,
            "duracion":   duracion,
            "productos":  row.total if row else 0,
            "enStock":    row.in_stock_count if row else 0,
            "errores":    0,
        })

    return result


@router.get("/tasks")
def get_tasks() -> list[dict[str, Any]]:
    import json
    r = _get_redis()
    running, active_task = _is_scraping(r)
    now = _now_lima()

    tasks = []

    # Tarea activa
    if running and active_task:
        tasks.append({
            "id":       active_task[:8],
            "fullId":   active_task,
            "tipo":     "scrape_all_stores",
            "status":   "Ejecutando",
            "inicio":   "ahora",
            "duracion": "en curso",
            "resultado": None,
            "error":    None,
        })

    # Historial reciente desde Redis (celery result backend)
    try:
        keys = r.keys("celery-task-meta-*")
        history = []
        for key in keys[:50]:
            raw = r.get(key)
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            task_id = data.get("task_id", "")
            status  = data.get("status", "")
            result  = data.get("result")

            state_map = {
                "SUCCESS": "Completado",
                "FAILURE": "Fallido",
                "STARTED": "Ejecutando",
                "PENDING": "Pendiente",
                "RETRY":   "Reintentando",
            }
            status_label = state_map.get(status, status)

            resumen = None
            error   = None
            if status == "SUCCESS" and isinstance(result, dict):
                total = sum(v.get("saved", 0) for v in result.values() if isinstance(v, dict))
                resumen = f"{total:,} productos guardados"
            elif status == "FAILURE":
                error = str(result)[:80] if result else "Error desconocido"

            history.append({
                "id":       task_id[:8] if task_id else "—",
                "fullId":   task_id,
                "tipo":     "scrape_all_stores",
                "status":   status_label,
                "inicio":   "—",
                "duracion": "—",
                "resultado": resumen,
                "error":    error,
            })

        tasks.extend(sorted(history, key=lambda x: x["status"] == "Completado", reverse=True)[:9])
    except Exception:
        pass

    return tasks[:10]


@router.get("/logs")
def get_logs() -> list[dict[str, Any]]:
    # Preparado para conectar con logs reales (tabla system_logs o archivo)
    now_str = _now_lima().strftime("%d/%m %H:%M")
    return [
        {"fecha": now_str, "modulo": "SodimacScraper",   "tipo": "INFO",    "mensaje": "Scrape completado correctamente",        "severidad": "info"},
        {"fecha": now_str, "modulo": "FalabellaScraper",  "tipo": "INFO",    "mensaje": "7,453 productos guardados",              "severidad": "info"},
        {"fecha": now_str, "modulo": "TelegramNotifier",  "tipo": "INFO",    "mensaje": "Alertas enviadas a 2 canales",           "severidad": "info"},
        {"fecha": now_str, "modulo": "RipleyScraper",     "tipo": "WARNING", "mensaje": "167 productos obtenidos (bajo promedio)","severidad": "warning"},
        {"fecha": now_str, "modulo": "CeleryBeat",        "tipo": "INFO",    "mensaje": "Próximo scrape programado correctamente","severidad": "info"},
    ]


@router.get("/syncs")
def get_syncs() -> list[dict[str, Any]]:
    from sqlalchemy import text
    r = _get_redis()
    running, _ = _is_scraping(r)
    now = _now_lima()

    with _get_db() as session:
        rows = session.execute(text("""
            SELECT store, MAX(last_scraped_at) AS last_sync
            FROM store_products
            GROUP BY store
        """)).fetchall()

    store_last = {row.store: row.last_sync for row in rows}

    # Próxima ejecución: siguiente hora del schedule
    next_slots = sorted(
        _BEAT_SCHEDULE,
        key=lambda s: (s["hour"] * 60 + s["minute"]) % (24 * 60)
    )
    next_time = "—"
    for slot in next_slots:
        nt = _next_run(slot["hour"], slot["minute"], now)
        next_time = nt
        break

    result = []
    for store in _STORES:
        last_dt = store_last.get(store)
        if last_dt:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
            mins_ago = (now - last_dt).total_seconds() / 60
            last_str = last_dt.strftime("%d/%m %H:%M")
            status = "Ejecutando" if running else ("Activo" if mins_ago < 180 else "Pausado")
        else:
            last_str = "Nunca"
            status = "Pausado"

        result.append({
            "store":        store.capitalize(),
            "ultimaSync":   last_str,
            "proximaSync":  next_time,
            "frecuencia":   "Cada ~2h",
            "status":       status,
        })

    return result


@router.post("/scrapers/{store_id}/run")
def run_scraper(store_id: str) -> dict[str, str]:
    from app.tasks.celery_app import scrape_all_stores
    import redis as _redis
    from app.core.config import get_settings
    task = scrape_all_stores.delay()
    try:
        r = _redis.from_url(get_settings().redis_url)
        r.set("scrape_active_task", task.id, ex=1800)
    except Exception:
        pass
    return {"status": "accepted", "task_id": task.id}
