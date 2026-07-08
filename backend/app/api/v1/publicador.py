"""Publicador IA.

Gestiona contenido generado por IA para múltiples canales:
Telegram, Facebook, Instagram, TikTok.

Flujo: Pendiente → Generar → Generado → Aprobar → Aprobado → Publicar → Publicado
       Aprobado → Programar → Programado → Publicar → Publicado

Regla: NADA se publica automáticamente; publicar requiere acción manual.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException

router = APIRouter(prefix="/publicador", tags=["publicador"])

_REDIS_KEY = "publicador:items"

ESTADOS = ["Pendiente", "Generado", "Aprobado", "Programado", "Publicado", "Error"]
CANALES = ["Telegram", "Facebook", "Instagram", "TikTok"]

_STORE_TAGS: dict[str, str] = {
    "falabella": "#Falabella", "ripley": "#Ripley", "plazavea": "#PlazaVea",
    "oechsle": "#Oechsle", "sodimac": "#Sodimac", "estilos": "#Estilos",
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


def _hashtags(store: str, category: str, disc: int) -> list[str]:
    cat_slug = (category or "general").lower().replace(" ", "").replace("/", "")
    tags = ["#ofertasperu", "#pricehunterpro", "#descuentos", "#peru"]
    tags.append(_STORE_TAGS.get(store, f"#{store.capitalize()}"))
    if disc >= 50:
        tags.append("#megaoferta")
    elif disc >= 30:
        tags.append("#superoferta")
    tags.append(f"#{cat_slug}")
    return tags


def _generar_contenido(
    canal: str, name: str, store: str, category: str,
    current: float, original: float, disc: int, url: str,
) -> str:
    tag_store = _STORE_TAGS.get(store, f"#{store.capitalize()}")
    cat_slug = (category or "general").lower()
    titulo = name[:60] + ("…" if len(name) > 60 else "")
    hashtags_line = " ".join(_hashtags(store, category, disc))

    if canal == "Telegram":
        return (
            f"🔥 ¡{disc}% OFF DETECTADO!\n\n"
            f"**{titulo}**\n\n"
            f"~~S/{original:.2f}~~ → **S/{current:.2f}**\n\n"
            f"🏪 {store.capitalize()} | 📂 {cat_slug.capitalize()}\n"
            f"👉 Link en este mensaje 👇\n\n"
            f"{hashtags_line}"
        )
    if canal == "Instagram":
        return (
            f"🔥 ¡{disc}% OFF!\n\n"
            f"{titulo}\n\n"
            f"Antes S/{original:.2f} → AHORA S/{current:.2f}\n\n"
            f"📍 {store.capitalize()} | {cat_slug.capitalize()}\n"
            f"👉 Link en bio 🔗\n\n"
            f"{hashtags_line} #instagram"
        )
    if canal == "TikTok":
        return (
            f"🔥 {disc}% OFF — ¡OFERTA DETECTADA!\n\n"
            f"{titulo}\n\n"
            f"Antes S/{original:.2f} → AHORA S/{current:.2f}\n\n"
            f"Tienda: {store.capitalize()} 🛒\n"
            f"👉 Link en bio 👇\n\n"
            f"{hashtags_line} #tiktok #fyp #viral"
        )
    # Facebook
    return (
        f"🔥 ¡{disc}% OFF!\n\n"
        f"📦 {titulo}\n\n"
        f"💰 Antes S/{original:.2f} → AHORA S/{current:.2f}\n\n"
        f"🏪 Disponible en {store.capitalize()}\n"
        f"👉 Link en los comentarios 👇\n\n"
        f"{hashtags_line}"
    )


def _seed_items() -> list[dict]:
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    from app.core.config import get_settings

    db_url = (
        get_settings().database_url
        .replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    )
    engine = create_engine(db_url)
    with Session(engine) as session:
        rows = session.execute(text("""
            SELECT p.id, p.name, sp.store, p.category,
                   CAST(sp.current_price        AS float) AS cp,
                   CAST(sp.original_price       AS float) AS op,
                   CAST(sp.discount_percentage  AS float) AS disc,
                   p.image_url, sp.url
            FROM store_products sp
            JOIN products p ON p.id = sp.product_id
            WHERE sp.in_stock = true
              AND sp.discount_percentage >= 25
              AND sp.current_price >= 15
            ORDER BY sp.discount_percentage DESC
            LIMIT 16
        """)).fetchall()

    estados_init = [
        "Pendiente", "Generado",  "Programado", "Publicado",
        "Aprobado",  "Programado", "Publicado",  "Programado",
        "Pendiente", "Error",     "Programado",  "Publicado",
        "Generado",  "Programado", "Publicado",  "Programado",
    ]
    scores = [95, 88, 92, 80, 87, 76, 83, 91, 70, 55, 78, 85, 93, 68, 82, 79]
    canales_sets = [
        ["Telegram", "Facebook"],
        ["Telegram", "Instagram"],
        ["Facebook", "Instagram"],
        ["TikTok"],
        ["Telegram"],
        ["Facebook", "TikTok"],
        ["Instagram", "TikTok"],
        ["Telegram", "Facebook", "Instagram"],
        ["Telegram"],
        ["Facebook"],
        ["Instagram"],
        ["TikTok", "Telegram"],
        ["Facebook", "Instagram", "TikTok"],
        ["Telegram", "Facebook"],
        ["Instagram"],
        ["TikTok"],
    ]

    items: list[dict] = []
    for i, row in enumerate(rows):
        disc = int(row.disc) if row.disc else 0
        canales_sel = canales_sets[i % len(canales_sets)]
        estado = estados_init[i % len(estados_init)]
        has_content = estado not in ("Pendiente", "Error")
        contenido = (
            _generar_contenido(
                canales_sel[0], row.name or "", row.store, row.category or "General",
                row.cp, row.op, disc, row.url or "",
            )
            if has_content else ""
        )
        # Fechas para el Calendario Editorial: Programado → futuro, Publicado → pasado
        now = datetime.now(timezone.utc)
        fecha_prog = None
        fecha_pub = None
        created = now
        if estado == "Programado":
            fecha_prog = (now + timedelta(days=(i % 18), hours=9 + (i % 8))).isoformat()
        elif estado == "Publicado":
            fecha_pub = (now - timedelta(days=1 + (i % 20), hours=(i % 12))).isoformat()
        else:
            created = now - timedelta(days=(i % 6), hours=(i % 10))
        items.append({
            "id":                   str(uuid.uuid4()),
            "opportunityId":        str(row.id),
            "titulo":               (row.name or "")[:70],
            "store":                row.store,
            "category":             row.category or "General",
            "currentPrice":         row.cp,
            "originalPrice":        row.op,
            "discountPct":          disc,
            "imageUrl":             row.image_url or "",
            "url":                  row.url or "",
            "canalesSeleccionados": canales_sel,
            "contenido":            contenido,
            "hashtags":             _hashtags(row.store, row.category or "General", disc),
            "scoreIA":              scores[i % len(scores)],
            "estado":               estado,
            "fechaProgramada":      fecha_prog,
            "fechaPublicacion":     fecha_pub,
            "generadoAt":           None if not has_content else now.isoformat(),
            "createdAt":            created.isoformat(),
        })

    _save_items(items)
    return items


def _kpis(items: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {e: 0 for e in ESTADOS}
    for it in items:
        e = it.get("estado", "Pendiente")
        counts[e] = counts.get(e, 0) + 1
    return {
        "total":       len(items),
        "pendientes":  counts["Pendiente"],
        "generados":   counts["Generado"],
        "aprobados":   counts["Aprobado"],
        "programados": counts["Programado"],
        "publicados":  counts["Publicado"],
        "errores":     counts["Error"],
    }


def _find(items: list[dict], item_id: str) -> dict:
    for it in items:
        if it["id"] == item_id:
            return it
    raise HTTPException(status_code=404, detail="Item no encontrado")


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
        filtered = [i for i in filtered if canal in i.get("canalesSeleccionados", [])]
    return {"items": filtered, "kpis": _kpis(items), "canales": CANALES, "estados": ESTADOS}


@router.post("/generar")
def generar(body: dict = Body(...)) -> dict[str, Any]:
    """Genera contenido IA para el item: Pendiente/Error → Generado."""
    items = _all_items()
    it = _find(items, body.get("id", ""))
    if it["estado"] not in ("Pendiente", "Error"):
        raise HTTPException(status_code=409, detail="Solo se puede generar para items Pendiente o Error")
    canales_sel = it.get("canalesSeleccionados") or ["Telegram"]
    canal_primary = canales_sel[0]
    it["contenido"] = _generar_contenido(
        canal_primary, it["titulo"], it["store"], it.get("category", "General"),
        it["currentPrice"], it["originalPrice"], it["discountPct"], it.get("url", ""),
    )
    it["hashtags"] = _hashtags(it["store"], it.get("category", "General"), it["discountPct"])
    it["estado"] = "Generado"
    it["generadoAt"] = datetime.now(timezone.utc).isoformat()
    _save_items(items)
    return {"status": "ok", "estado": "Generado", "item": it}


@router.post("/aprobar")
def aprobar(body: dict = Body(...)) -> dict[str, str]:
    items = _all_items()
    it = _find(items, body.get("id", ""))
    if it["estado"] != "Generado":
        raise HTTPException(status_code=409, detail="Solo se puede aprobar un item Generado")
    it["estado"] = "Aprobado"
    _save_items(items)
    return {"status": "ok", "estado": "Aprobado"}


@router.post("/programar")
def programar(body: dict = Body(...)) -> dict[str, str]:
    items = _all_items()
    it = _find(items, body.get("id", ""))
    fecha = body.get("fecha", "")
    if not fecha:
        raise HTTPException(status_code=400, detail="Falta la fecha de programación")
    it["estado"] = "Programado"
    it["fechaProgramada"] = fecha
    _save_items(items)
    return {"status": "ok", "estado": "Programado", "fecha": fecha}


@router.post("/publicar")
def publicar(body: dict = Body(...)) -> dict[str, str]:
    """Publica manualmente. Solo si está Aprobado o Programado."""
    items = _all_items()
    it = _find(items, body.get("id", ""))
    if it["estado"] not in ("Aprobado", "Programado"):
        raise HTTPException(
            status_code=409,
            detail="Solo se puede publicar un item Aprobado o Programado",
        )
    it["estado"] = "Publicado"
    it["fechaPublicacion"] = datetime.now(timezone.utc).isoformat()
    _save_items(items)
    return {"status": "ok", "estado": "Publicado"}


@router.post("/update")
def update(body: dict = Body(...)) -> dict[str, Any]:
    """Editar contenido, hashtags o canales seleccionados."""
    items = _all_items()
    it = _find(items, body.get("id", ""))
    if "titulo" in body:
        it["titulo"] = str(body["titulo"])[:70]
    if "contenido" in body:
        it["contenido"] = str(body["contenido"])
    if "hashtags" in body and isinstance(body["hashtags"], list):
        it["hashtags"] = [str(h) for h in body["hashtags"]]
    if "canalesSeleccionados" in body and isinstance(body["canalesSeleccionados"], list):
        it["canalesSeleccionados"] = [str(c) for c in body["canalesSeleccionados"]]
    if it["estado"] == "Error":
        it["estado"] = "Generado"
    _save_items(items)
    return {"status": "ok", "item": it}


@router.post("/reload")
def reload_items() -> dict[str, Any]:
    """Recarga los items desde la BD (borra los actuales)."""
    _r().delete(_REDIS_KEY)
    items = _seed_items()
    return {"status": "ok", "count": len(items)}


# ── Calendario Editorial ────────────────────────────────────────────────────

# Estados del calendario (4). Los estados internos Generado/Aprobado se agrupan
# como "Pendiente" (contenido listo pero aún sin programar/publicar).
CAL_ESTADOS = ["Publicado", "Programado", "Pendiente", "Error"]


def _cal_estado(estado: str) -> str:
    if estado in ("Publicado", "Programado", "Error"):
        return estado
    return "Pendiente"  # Pendiente, Generado, Aprobado


def _cal_fecha(it: dict) -> str | None:
    """Fecha en la que el item cae en el calendario según su estado."""
    if it.get("estado") == "Publicado" and it.get("fechaPublicacion"):
        return it["fechaPublicacion"]
    if it.get("estado") == "Programado" and it.get("fechaProgramada"):
        return it["fechaProgramada"]
    return it.get("fechaProgramada") or it.get("fechaPublicacion") or it.get("createdAt")


@router.get("/calendario")
def calendario() -> dict[str, Any]:
    """Eventos para el Calendario Editorial, integrados con el Publicador IA.
    Reutiliza los mismos items (Redis): cada uno se ubica en una fecha según su
    estado y se mapea a uno de los 4 estados del calendario."""
    items = _all_items()
    if not items:
        items = _seed_items()

    eventos = []
    kpis = {e: 0 for e in CAL_ESTADOS}
    for it in items:
        cal_estado = _cal_estado(it.get("estado", "Pendiente"))
        kpis[cal_estado] += 1
        eventos.append({
            "id":          it["id"],
            "titulo":      it.get("titulo", ""),
            "store":       it.get("store", ""),
            "category":    it.get("category", ""),
            "discountPct": it.get("discountPct", 0),
            "currentPrice": it.get("currentPrice", 0),
            "imageUrl":    it.get("imageUrl", ""),
            "canales":     it.get("canalesSeleccionados", []),
            "estado":      cal_estado,
            "estadoReal":  it.get("estado", "Pendiente"),
            "fecha":       _cal_fecha(it),
        })

    return {"eventos": eventos, "kpis": kpis, "estados": CAL_ESTADOS, "total": len(eventos)}
