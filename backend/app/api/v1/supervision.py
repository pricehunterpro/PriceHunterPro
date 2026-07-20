"""Bandeja de Supervisión (PASO 7).

Módulo para revisar, aprobar, rechazar o programar publicaciones generadas por
PriceHunter Pro para varios canales (Telegram, Facebook, Instagram, TikTok).

Regla de negocio: NADA se publica automáticamente; publicar requiere acción
manual vía POST /supervision/publish.

Persistencia en Redis (mismo patrón que el módulo TikTok), sembrada desde los
mejores deals de la BD.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException

router = APIRouter(prefix="/supervision", tags=["supervision"])

_REDIS_KEY = "supervision:items"

# Estados del flujo de supervisión
ESTADOS = [
    "Pendiente", "Generado", "En revisión", "Aprobado",
    "Programado", "Publicado", "Rechazado", "Error",
]
CANALES = ["Telegram", "Facebook", "Instagram", "TikTok"]

_STORE_TAGS: dict[str, str] = {
    "falabella": "#falabella", "ripley": "#ripley", "plazavea": "#plazavea",
    "oechsle": "#oechsle", "sodimac": "#sodimac", "estilos": "#estilos",
    "shopstar": "#shopstar",
}


def _r():
    import redis as _redis
    from app.core.config import get_settings
    return _redis.from_url(get_settings().redis_url)


def _all_items() -> list[dict]:
    raw = _r().get(_REDIS_KEY) or b"[]"
    return json.loads(raw)


def _save_items(items: list[dict]) -> None:
    _r().set(_REDIS_KEY, json.dumps(items, default=str))


def _contenido(canal: str, name: str, store: str, current: float, original: float, disc: int) -> str:
    """Genera el texto de la publicación adaptado al canal."""
    tag = _STORE_TAGS.get(store, f"#{store}")
    tags = f"#ofertasperu #pricehunterpro #descuentos {tag} #peru"
    base = (
        f"🔥 ¡GANGA DETECTADA!\n\n{name[:70]}\n\n"
        f"Antes S/{original:.2f}  →  Ahora S/{current:.2f}\n"
        f"{disc}% OFF 🔥\n\nDisponible en {store.capitalize()}"
    )
    if canal == "Telegram":
        return f"{base}\n👉 Link en el mensaje\n\n{tags}"
    if canal == "Instagram":
        return f"{base}\n👉 Link en bio\n\n{tags}"
    if canal == "TikTok":
        return f"{base}\n👉 Link en bio 👇\n\n{tags}"
    return f"{base}\n👉 Más info en los comentarios\n\n{tags}"  # Facebook


def _seed_items() -> list[dict]:
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    from app.core.config import get_settings

    engine = create_engine(
        get_settings().database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    )
    with Session(engine) as session:
        rows = session.execute(text("""
            SELECT p.id, p.name, sp.store, p.category,
                   CAST(sp.current_price   AS float) AS cp,
                   CAST(sp.original_price  AS float) AS op,
                   CAST(sp.discount_percentage AS float) AS disc,
                   p.image_url, sp.url
            FROM store_products sp
            JOIN products p ON p.id = sp.product_id
            WHERE sp.in_stock = true AND sp.discount_percentage >= 30 AND sp.current_price >= 20
            ORDER BY sp.discount_percentage DESC
            LIMIT 12
        """)).fetchall()

    # Distribución inicial de estados (nada en "Publicado" hasta aprobación manual)
    estados = ["Pendiente", "Generado", "En revisión", "Aprobado", "Programado",
               "Pendiente", "Generado", "En revisión", "Rechazado", "Aprobado",
               "Pendiente", "Error"]
    scores = [96, 91, 88, 84, 80, 77, 74, 71, 68, 90, 86, 60]
    items: list[dict] = []

    for i, row in enumerate(rows):
        disc = int(row.disc) if row.disc else 0
        canal = CANALES[i % len(CANALES)]
        items.append({
            "id":               str(uuid.uuid4()),
            "opportunityId":    str(row.id),
            "titulo":           (row.name or "")[:70],
            "store":            row.store,
            "category":         row.category or "General",
            "currentPrice":     row.cp,
            "originalPrice":    row.op,
            "discountPct":      disc,
            "imageUrl":         row.image_url or "",
            "url":              row.url or "",
            "canal":            canal,
            "contenido":        _contenido(canal, row.name or "", row.store, row.cp, row.op, disc),
            "scoreIA":          scores[i % len(scores)],
            "estado":           estados[i % len(estados)],
            "fechaProgramada":  None,
            "fechaPublicacion": None,
            "motivoRechazo":    None,
            "createdAt":        datetime.now(timezone.utc).isoformat(),
        })

    _save_items(items)
    return items


def _kpis(items: list[dict]) -> dict[str, int]:
    counts = {e: 0 for e in ESTADOS}
    for it in items:
        counts[it.get("estado", "Pendiente")] = counts.get(it.get("estado", "Pendiente"), 0) + 1
    return {
        "total":       len(items),
        "pendientes":  counts["Pendiente"] + counts["Generado"],
        "enRevision":  counts["En revisión"],
        "aprobados":   counts["Aprobado"],
        "programados": counts["Programado"],
        "publicados":  counts["Publicado"],
        "rechazados":  counts["Rechazado"],
        "errores":     counts["Error"],
    }


def _find(items: list[dict], item_id: str) -> dict:
    for it in items:
        if it["id"] == item_id:
            return it
    raise HTTPException(status_code=404, detail="Publicación no encontrada")


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/items")
def get_items(estado: str | None = None, canal: str | None = None) -> dict[str, Any]:
    items = _all_items()
    if not items:
        items = _seed_items()
    filtered = items
    if estado:
        filtered = [i for i in filtered if i.get("estado") == estado]
    if canal:
        filtered = [i for i in filtered if i.get("canal") == canal]
    return {"items": filtered, "kpis": _kpis(items), "canales": CANALES, "estados": ESTADOS}


@router.post("/approve")
def approve(body: dict = Body(...)) -> dict[str, str]:
    items = _all_items()
    it = _find(items, body.get("id", ""))
    it["estado"] = "Aprobado"
    it["motivoRechazo"] = None
    _save_items(items)
    return {"status": "ok", "estado": "Aprobado"}


@router.post("/reject")
def reject(body: dict = Body(...)) -> dict[str, str]:
    items = _all_items()
    it = _find(items, body.get("id", ""))
    it["estado"] = "Rechazado"
    it["motivoRechazo"] = body.get("motivo", "")
    _save_items(items)
    return {"status": "ok", "estado": "Rechazado"}


@router.post("/schedule")
def schedule(body: dict = Body(...)) -> dict[str, str]:
    items = _all_items()
    it = _find(items, body.get("id", ""))
    fecha = body.get("fecha", "")
    if not fecha:
        raise HTTPException(status_code=400, detail="Falta la fecha de programación")
    it["estado"] = "Programado"
    it["fechaProgramada"] = fecha
    _save_items(items)
    return {"status": "ok", "estado": "Programado", "fecha": fecha}


@router.post("/publish")
def publish(body: dict = Body(...)) -> dict[str, str]:
    """Publica manualmente. Solo se permite si está Aprobado o Programado
    (nunca automático, según regla de negocio)."""
    items = _all_items()
    it = _find(items, body.get("id", ""))
    if it["estado"] not in ("Aprobado", "Programado"):
        raise HTTPException(
            status_code=409,
            detail="Solo se puede publicar una publicación Aprobada o Programada",
        )
    it["estado"] = "Publicado"
    it["fechaPublicacion"] = datetime.now(timezone.utc).isoformat()
    _save_items(items)
    return {"status": "ok", "estado": "Publicado"}


@router.post("/update")
def update(body: dict = Body(...)) -> dict[str, Any]:
    """Editar el contenido/título de una publicación (botón Editar)."""
    items = _all_items()
    it = _find(items, body.get("id", ""))
    if "titulo" in body:
        it["titulo"] = str(body["titulo"])[:70]
    if "contenido" in body:
        it["contenido"] = str(body["contenido"])
    if it["estado"] in ("Rechazado", "Error"):
        it["estado"] = "En revisión"
    _save_items(items)
    return {"status": "ok", "item": it}
