"""Scrapers — consola de administración y control de los scrapers.

- Registro (metadatos + config + estado) en Redis (`scrapers:registry`).
- Estadísticas reales desde la BD (`store_products`, `price_history`) e historial
  desde `scraping_logs` + runs propios.
- Ejecución single-store real en hilo daemon, con lock por scraper (regla 1: no
  dos ejecuciones simultáneas). Tras 3 fallos consecutivos: estado Error + alerta
  en el Centro de Monitoreo (regla 2). Preparado para migrar a Celery (regla 7).

No modifica ningún módulo existente.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time as _time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException

router = APIRouter(prefix="/scrapers", tags=["scrapers"])

_KEY = "scrapers:registry"

# Inventario real de scrapers (store, nombre, tipo, url base, estado inicial)
_META = [
    ("falabella",    "Falabella",     "Requests", "https://www.falabella.com.pe/falabella-pe", "Activo"),
    ("ripley",       "Ripley",        "Requests", "https://simple.ripley.com.pe",              "Activo"),
    ("plazavea",     "Plaza Vea",     "VTEX",     "https://www.plazavea.com.pe",               "Activo"),
    ("oechsle",      "Oechsle",       "VTEX",     "https://www.oechsle.pe",                    "Activo"),
    ("estilos",      "Estilos",       "VTEX",     "https://www.estilos.com.pe",                "Activo"),
    ("sodimac",      "Sodimac",       "Requests", "https://www.sodimac.com.pe/sodimac-pe",     "Activo"),
    ("mercadolibre", "Mercado Libre", "Requests", "https://www.mercadolibre.com.pe",           "Activo"),
    ("shopstar",     "Shopstar",      "VTEX",     "https://www.shopstar.pe",                   "Activo"),
    ("tottus",       "Tottus",        "VTEX",     "https://www.tottus.com.pe",                 "Deshabilitado"),
]
_SCHEDULES = ["Cada 15 minutos", "Cada 30 minutos", "Cada hora", "Cada 2 horas", "Cada 6 horas", "Manual"]
_TYPES = ["Playwright", "API", "Selenium", "Requests", "VTEX"]


def _r():
    import redis as _redis
    from app.core.config import get_settings
    return _redis.from_url(get_settings().redis_url)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_config() -> dict:
    return {
        "frecuencia": "Cada hora", "timeout": 30, "max_reintentos": 3,
        "delay_paginas": 0.5, "max_paginas": 6, "user_agent": "rotativo",
        "proxy": "", "headless": True, "debug": False,
    }


def _nuevo(store: str, nombre: str, tipo: str, url: str, estado: str) -> dict:
    now = _now()
    return {
        "id": store, "store_name": nombre, "scraper_name": f"{nombre}Scraper",
        "scraper_type": tipo, "base_url": url, "method": "GET",
        "status": estado, "schedule": "Cada hora" if estado == "Activo" else "Manual",
        "last_execution": None, "next_execution": None,
        "average_time": 0.0, "max_time": 0.0, "min_time": 0.0,
        "total_products": 0, "new_products": 0, "updated_products": 0, "errors": 0,
        "consecutive_failures": 0,
        "configuration_json": _default_config(),
        "created_at": now, "updated_at": now,
    }


def _seed() -> list[dict]:
    items = [_nuevo(*meta) for meta in _META]
    _r().set(_KEY, json.dumps(items, default=str))
    return items


def _all() -> list[dict]:
    """Devuelve el registro, incorporando los scrapers de _META que aún no estén.

    El registro vive en Redis y antes solo se sembraba con la key vacía, así que
    un scraper nuevo no aparecía nunca en un entorno ya arrancado (había que
    borrar la key a mano). Se reconcilia contra _META en cada lectura, sin tocar
    las entradas existentes para no pisar lo que el usuario haya configurado.
    """
    raw = _r().get(_KEY)
    if not raw:
        return _seed()
    items = json.loads(raw)
    conocidos = {it.get("id") for it in items}
    faltantes = [_nuevo(*meta) for meta in _META if meta[0] not in conocidos]
    if faltantes:
        items.extend(faltantes)
        _r().set(_KEY, json.dumps(items, default=str))
    return items


def _save(items: list[dict]) -> None:
    _r().set(_KEY, json.dumps(items, default=str))


def _find(items: list[dict], sid: str) -> dict:
    for it in items:
        if it["id"] == sid:
            return it
    raise HTTPException(status_code=404, detail="Scraper no encontrado")


# ── Stats reales desde la BD ─────────────────────────────────────────────────
def _db_counts() -> dict[str, int]:
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    from app.services.deal_service import _engine
    out: dict[str, int] = {}
    try:
        with Session(_engine) as s:
            for row in s.execute(text("SELECT store, COUNT(*) FROM store_products GROUP BY store")).all():
                out[row[0]] = int(row[1])
    except Exception:
        pass
    return out


def _products_today() -> int:
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    from app.services.deal_service import _engine
    try:
        with Session(_engine) as s:
            return int(s.execute(text(
                "SELECT COUNT(*) FROM price_history WHERE scraped_at >= date_trunc('day', NOW())"
            )).scalar() or 0)
    except Exception:
        return 0


def _enrich(items: list[dict]) -> list[dict]:
    counts = _db_counts()
    for it in items:
        it["total_products"] = counts.get(it["id"], it.get("total_products", 0))
    return items


# ── Endpoints de lectura ─────────────────────────────────────────────────────
@router.get("")
def list_scrapers() -> dict[str, Any]:
    items = _enrich(_all())
    return {"items": items, "types": _TYPES, "schedules": _SCHEDULES}


@router.get("/stats")
def stats() -> dict[str, Any]:
    items = _enrich(_all())
    def cnt(*st): return sum(1 for i in items if i["status"] in st)
    times = [i["average_time"] for i in items if i.get("average_time")]
    ult = max((i["last_execution"] for i in items if i.get("last_execution")), default=None)
    return {
        "kpis": {
            "registrados":       len(items),
            "activos":           cnt("Activo", "Ejecutando"),
            "detenidos":         cnt("Pausado", "Deshabilitado"),
            "conError":          cnt("Error"),
            "productosHoy":      _products_today(),
            "tiempoPromedio":    round(sum(times) / len(times), 1) if times else 0.0,
            "ultimaSincronizacion": ult,
        },
    }


@router.get("/history/{sid}")
def history(sid: str) -> dict[str, Any]:
    _find(_all(), sid)  # 404 si no existe
    runs_raw = _r().get(f"scraper:runs:{sid}")
    runs = json.loads(runs_raw) if runs_raw else []
    if runs:
        return {"items": runs[:20]}

    # Fallback: historial desde scraping_logs
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    from app.services.deal_service import _engine
    import re
    out = []
    try:
        with Session(_engine) as s:
            rows = s.execute(text("""
                SELECT status, details, error, created_at FROM scraping_logs
                WHERE store = :st ORDER BY created_at DESC LIMIT 20
            """), {"st": sid}).all()
            for st, details, error, created in rows:
                m = re.search(r"saved=(\d+)", details or "")
                me = re.search(r"errors=(\d+)", details or "")
                out.append({
                    "fecha": created.isoformat() if created else None,
                    "duracion": None,
                    "productos": int(m.group(1)) if m else 0,
                    "errores": int(me.group(1)) if me else 0,
                    "estado": "success" if st == "success" else "error",
                })
    except Exception:
        pass
    return {"items": out}


@router.get("/{sid}")
def get_one(sid: str) -> dict[str, Any]:
    it = _find(_enrich(_all()), sid)
    return {"item": it}


# ── Control ──────────────────────────────────────────────────────────────────
def _push_monitor(store_label: str, mensaje: str, severidad: str = "error") -> None:
    """Alerta al Centro de Monitoreo (misma lista Redis `system:logs`)."""
    try:
        entry = json.dumps({
            "fecha": datetime.now(timezone.utc).strftime("%d/%m %H:%M"),
            "modulo": store_label, "tipo": severidad.upper(),
            "mensaje": mensaje, "severidad": severidad,
        })
        r = _r()
        r.lpush("system:logs", entry)
        r.ltrim("system:logs", 0, 199)
    except Exception:
        pass


_SCRAPER_CLASSES = {
    "falabella": "FalabellaScraper", "ripley": "RipleyScraper", "plazavea": "PlazaVeaScraper",
    "oechsle": "OechsleScraper", "estilos": "EstilosScraper", "sodimac": "SodimacScraper",
    "tottus": "TottusScraper", "mercadolibre": "MercadoLibreScraper",
    "shopstar": "ShopstarScraper",
}


def _get_scraper(store: str):
    import importlib
    cls = _SCRAPER_CLASSES.get(store)
    if not cls:
        raise RuntimeError(f"Scraper desconocido: {store}")
    mod = importlib.import_module(f"app.scrapers.{store}_scraper")
    return getattr(mod, cls)()


def _record_run(store: str, run: dict) -> None:
    r = _r()
    raw = r.get(f"scraper:runs:{store}")
    runs = json.loads(raw) if raw else []
    runs.insert(0, run)
    r.set(f"scraper:runs:{store}", json.dumps(runs[:20], default=str))


def _run_scraper_bg(store: str) -> None:
    from sqlalchemy import text as sql_text
    from sqlalchemy.orm import Session
    from app.services.deal_service import _engine
    from app.repositories.product_repo import bulk_upsert_store, log_scraping

    r = _r()
    start = _time.time()
    ok, saved, errors, err_msg = False, 0, 0, ""
    try:
        scraper = _get_scraper(store)
        products = asyncio.run(scraper.get_category())
        with Session(_engine) as session:
            saved, errors, seen_ids = bulk_upsert_store(session, store, products)
            if seen_ids:
                session.execute(sql_text(
                    "UPDATE store_products SET in_stock=false WHERE store=:s AND id != ALL(:ids) AND in_stock=true"
                ), {"s": store, "ids": seen_ids})
            log_scraping(session, store, "success", details=f"saved={saved} errors={errors} (manual)")
            session.commit()
        ok = True
    except Exception as exc:
        err_msg = str(exc)[:300]
        try:
            with Session(_engine) as session:
                log_scraping(session, store, "error", error=err_msg)
                session.commit()
        except Exception:
            pass

    duration = round(_time.time() - start, 1)

    # Actualizar registro
    items = _all()
    it = next((i for i in items if i["id"] == store), None)
    if it:
        it["last_execution"] = _now()
        it["errors"] = errors if ok else it.get("errors", 0) + 1
        if ok:
            it["new_products"] = saved
            it["consecutive_failures"] = 0
            it["status"] = "Activo" if it["status"] != "Deshabilitado" else it["status"]
            # tiempos
            prev = it.get("average_time", 0) or 0
            it["average_time"] = round((prev + duration) / 2, 1) if prev else duration
            it["max_time"] = max(it.get("max_time", 0) or 0, duration)
            it["min_time"] = duration if not it.get("min_time") else min(it["min_time"], duration)
        else:
            it["consecutive_failures"] = it.get("consecutive_failures", 0) + 1
            if it["consecutive_failures"] >= 3:
                it["status"] = "Error"
                _push_monitor(it["store_name"] + "Scraper",
                              f"{it['store_name']}: 3 fallos consecutivos, scraper en Error", "error")
            else:
                it["status"] = "Activo" if it["status"] not in ("Deshabilitado",) else it["status"]
        it["updated_at"] = _now()
        _save(items)

    _record_run(store, {
        "fecha": _now(), "duracion": duration,
        "productos": saved if ok else 0, "errores": errors if ok else 1,
        "estado": "success" if ok else "error", "mensaje": err_msg,
    })
    r.delete(f"scraper:lock:{store}")


@router.post("/run/{sid}")
def run(sid: str) -> dict[str, Any]:
    items = _all()
    it = _find(items, sid)
    if it["status"] == "Pausado":
        raise HTTPException(status_code=409, detail="El scraper está pausado. Reanúdalo antes de ejecutar.")

    r = _r()
    lock = f"scraper:lock:{sid}"
    if r.exists(lock) or it["status"] == "Ejecutando":
        raise HTTPException(status_code=409, detail="Este scraper ya se está ejecutando")

    r.set(lock, "1", ex=1800)
    it["status"] = "Ejecutando"
    it["updated_at"] = _now()
    _save(items)

    threading.Thread(target=_run_scraper_bg, args=(sid,), daemon=True).start()
    return {"status": "ok", "message": f"Ejecutando scraper {it['store_name']}", "estado": "Ejecutando"}


@router.post("/pause/{sid}")
def pause(sid: str) -> dict[str, str]:
    items = _all()
    it = _find(items, sid)
    it["status"] = "Pausado"
    it["updated_at"] = _now()
    _save(items)
    return {"status": "ok", "estado": "Pausado"}


@router.post("/resume/{sid}")
def resume(sid: str) -> dict[str, str]:
    items = _all()
    it = _find(items, sid)
    it["status"] = "Activo"
    it["consecutive_failures"] = 0
    it["updated_at"] = _now()
    _save(items)
    return {"status": "ok", "estado": "Activo"}


@router.post("/retry/{sid}")
def retry(sid: str) -> dict[str, Any]:
    items = _all()
    it = _find(items, sid)
    it["consecutive_failures"] = 0
    if it["status"] == "Error":
        it["status"] = "Activo"
    _save(items)
    return run(sid)


@router.put("/config/{sid}")
def update_config(sid: str, body: dict = Body(...)) -> dict[str, Any]:
    items = _all()
    it = _find(items, sid)
    cfg = it.get("configuration_json", _default_config())
    for k in ("frecuencia", "timeout", "max_reintentos", "delay_paginas",
              "max_paginas", "user_agent", "proxy", "headless", "debug"):
        if k in body:
            cfg[k] = body[k]
    it["configuration_json"] = cfg
    if body.get("schedule") in _SCHEDULES:
        it["schedule"] = body["schedule"]
        cfg["frecuencia"] = body["schedule"]
    if body.get("scraper_type") in _TYPES:
        it["scraper_type"] = body["scraper_type"]
    it["updated_at"] = _now()
    _save(items)
    return {"status": "ok", "item": it}
