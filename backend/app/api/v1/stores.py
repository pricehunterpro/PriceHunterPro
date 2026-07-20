"""Tiendas — administración de las tiendas monitoreadas.

Gestiona los datos de negocio de cada tienda (nombre, logo, color, dominio,
categoría, URL, frecuencia) en un registro Redis (`stores:registry`), y se
RELACIONA con el módulo Scrapers (mismo id de tienda): productos, último
scraping, tiempo promedio y errores se leen del registro de scrapers + BD.
Permite agregar nuevas tiendas sin tocar código (el registro es dinámico).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException

router = APIRouter(prefix="/stores", tags=["stores"])

_KEY = "stores:registry"

TIPOS = ["Playwright", "API", "Selenium", "Requests", "VTEX"]
CATEGORIAS = ["Retail", "Marketplace", "Supermercado", "Mejoramiento del hogar", "Moda", "Tecnología"]
FRECUENCIAS = ["Cada 15 minutos", "Cada 30 minutos", "Cada hora", "Cada 2 horas", "Cada 6 horas", "Manual"]

# Branding real de las tiendas
_META = [
    ("falabella",    "Falabella",     "falabella.com.pe",     "Requests", "Retail",                "#22c55e"),
    ("ripley",       "Ripley",        "simple.ripley.com.pe", "Requests", "Retail",                "#8b5cf6"),
    ("plazavea",     "Plaza Vea",     "plazavea.com.pe",      "VTEX",     "Supermercado",          "#e11d48"),
    ("oechsle",      "Oechsle",       "oechsle.pe",           "VTEX",     "Retail",                "#e01a2b"),
    ("estilos",      "Estilos",       "estilos.com.pe",       "VTEX",     "Moda",                  "#ec4899"),
    ("sodimac",      "Sodimac",       "sodimac.com.pe",       "Requests", "Mejoramiento del hogar","#ff6b00"),
    ("mercadolibre", "Mercado Libre", "mercadolibre.com.pe",  "Requests", "Marketplace",           "#ffe036"),
    ("shopstar",     "Shopstar",      "shopstar.pe",          "VTEX",     "Marketplace",           "#00b8a9"),
    ("tottus",       "Tottus",        "tottus.com.pe",        "VTEX",     "Supermercado",          "#3c64c8"),
]


def _r():
    import redis as _redis
    from app.core.config import get_settings
    return _redis.from_url(get_settings().redis_url)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _nuevo(sid: str, nombre: str, dominio: str, tipo: str, cat: str, color: str) -> dict:
    now = _now()
    return {
        "id": sid, "nombre": nombre, "logo": nombre[:1].upper(), "dominio": dominio,
        "tipo": tipo, "scraper_asociado": sid, "estado": "Activo" if sid != "tottus" else "Inactivo",
        "color": color, "categoria": cat, "url": f"https://www.{dominio}",
        "frecuencia": "Cada hora" if sid != "tottus" else "Manual",
        "created_at": now, "updated_at": now,
    }


def _seed() -> list[dict]:
    items = [_nuevo(*meta) for meta in _META]
    _r().set(_KEY, json.dumps(items, default=str))
    return items


def _all() -> list[dict]:
    """Devuelve el registro, incorporando las tiendas de _META que aún no estén.

    El registro vive en Redis y antes solo se sembraba con la key vacía, así que
    una tienda nueva no aparecía nunca en un entorno ya arrancado (había que
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
    raise HTTPException(status_code=404, detail="Tienda no encontrada")


# ── Relación con Scrapers + BD ───────────────────────────────────────────────
def _scraper_registry() -> dict[str, dict]:
    raw = _r().get("scrapers:registry")
    if not raw:
        return {}
    return {s["id"]: s for s in json.loads(raw)}


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


def _enrich(items: list[dict]) -> list[dict]:
    scr = _scraper_registry()
    counts = _db_counts()
    for it in items:
        s = scr.get(it["scraper_asociado"], {})
        it["productos"] = counts.get(it["id"], 0)
        it["ultimoScraping"] = s.get("last_execution")
        it["tiempoPromedio"] = s.get("average_time", 0)
        it["errores"] = s.get("errors", 0)
        it["ultimaSincronizacion"] = s.get("last_execution")
        it["scraperEstado"] = s.get("status", "—")
    return items


# ── Lectura ──────────────────────────────────────────────────────────────────
@router.get("")
def list_stores() -> dict[str, Any]:
    items = _enrich(_all())
    return {"items": items, "tipos": TIPOS, "categorias": CATEGORIAS, "frecuencias": FRECUENCIAS}


@router.get("/stats")
def stats() -> dict[str, Any]:
    items = _enrich(_all())
    return {
        "kpis": {
            "totalTiendas":       len(items),
            "activas":            sum(1 for i in items if i["estado"] == "Activo"),
            "inactivas":          sum(1 for i in items if i["estado"] != "Activo"),
            "productosTotales":   sum(i.get("productos", 0) for i in items),
            "conError":           sum(1 for i in items if i.get("scraperEstado") == "Error"),
        },
    }


@router.get("/{sid}")
def get_one(sid: str) -> dict[str, Any]:
    return {"item": _find(_enrich(_all()), sid)}


# ── CRUD ─────────────────────────────────────────────────────────────────────
@router.post("")
def create(body: dict = Body(...)) -> dict[str, Any]:
    nombre = (body.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio")
    sid = (body.get("id") or nombre.lower().replace(" ", "")).strip()
    items = _all()
    if any(i["id"] == sid for i in items):
        raise HTTPException(status_code=400, detail="Ya existe una tienda con ese identificador")
    now = _now()
    it = {
        "id": sid, "nombre": nombre[:80], "logo": nombre[:1].upper(),
        "dominio": body.get("dominio") or "", "tipo": body.get("tipo") if body.get("tipo") in TIPOS else "Requests",
        "scraper_asociado": body.get("scraper_asociado") or sid,
        "estado": body.get("estado") if body.get("estado") in ("Activo", "Inactivo") else "Inactivo",
        "color": body.get("color") or "#00E58F",
        "categoria": body.get("categoria") if body.get("categoria") in CATEGORIAS else "Retail",
        "url": body.get("url") or (f"https://www.{body.get('dominio')}" if body.get("dominio") else ""),
        "frecuencia": body.get("frecuencia") if body.get("frecuencia") in FRECUENCIAS else "Manual",
        "created_at": now, "updated_at": now,
    }
    items.append(it)
    _save(items)
    return {"status": "ok", "item": it}


@router.put("/{sid}")
def update(sid: str, body: dict = Body(...)) -> dict[str, Any]:
    items = _all()
    it = _find(items, sid)
    for f in ("nombre", "dominio", "url", "color", "scraper_asociado"):
        if f in body:
            it[f] = body[f]
    if body.get("tipo") in TIPOS: it["tipo"] = body["tipo"]
    if body.get("categoria") in CATEGORIAS: it["categoria"] = body["categoria"]
    if body.get("frecuencia") in FRECUENCIAS: it["frecuencia"] = body["frecuencia"]
    if body.get("estado") in ("Activo", "Inactivo"): it["estado"] = body["estado"]
    if body.get("nombre"): it["logo"] = str(body["nombre"])[:1].upper()
    it["updated_at"] = _now()
    _save(items)
    return {"status": "ok", "item": it}


@router.post("/{sid}/toggle")
def toggle(sid: str) -> dict[str, Any]:
    items = _all()
    it = _find(items, sid)
    it["estado"] = "Inactivo" if it["estado"] == "Activo" else "Activo"
    it["updated_at"] = _now()
    _save(items)
    return {"status": "ok", "item": it}


@router.delete("/{sid}")
def delete(sid: str) -> dict[str, str]:
    items = _all()
    _find(items, sid)
    _save([i for i in items if i["id"] != sid])
    return {"status": "ok"}


# ── Relación con Scrapers: probar scraper / ver historial ────────────────────
@router.post("/{sid}/test")
def test_scraper(sid: str) -> dict[str, Any]:
    it = _find(_all(), sid)
    try:
        from app.api.v1.scrapers import run as run_scraper
        return run_scraper(it["scraper_asociado"])
    except HTTPException as e:
        raise e
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo probar el scraper: {exc}")


@router.get("/{sid}/history")
def history(sid: str) -> dict[str, Any]:
    it = _find(_all(), sid)
    try:
        from app.api.v1.scrapers import history as scraper_history
        return scraper_history(it["scraper_asociado"])
    except Exception:
        return {"items": []}
