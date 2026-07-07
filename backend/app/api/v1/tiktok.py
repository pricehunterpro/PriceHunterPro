from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body

router = APIRouter(prefix="/tiktok", tags=["tiktok"])

_STORE_TAGS: dict[str, str] = {
    "falabella": "#falabella", "ripley": "#ripley",
    "plazavea": "#plazavea", "oechsle": "#oechsle",
    "sodimac": "#sodimac", "estilos": "#estilos",
}
_PLANTILLAS = ["Flash Sale", "Mega Oferta", "Gaming", "Tecnología", "Hogar", "Top Oferta del Día"]


def _r():
    import redis as _redis
    from app.core.config import get_settings
    return _redis.from_url(get_settings().redis_url)


def _all_videos() -> list[dict]:
    raw = _r().get("tiktok:videos") or b"[]"
    return json.loads(raw)


def _save_videos(videos: list[dict]) -> None:
    _r().set("tiktok:videos", json.dumps(videos, default=str))


def _build_guion(name: str, store: str, current: float, original: float, disc: int, tags: list[str]) -> str:
    return (
        f"🔥 GANGA DETECTADA\n\n"
        f"{name[:50]}\n\n"
        f"Antes S/{original:.2f}\n"
        f"Ahora S/{current:.2f}\n\n"
        f"{disc}% OFF 🔥\n\n"
        f"Disponible en {store.capitalize()}\n"
        f"Link en bio 👇\n\n"
        f"{' '.join(tags)}"
    )


def _seed_videos() -> list[dict]:
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
            LIMIT 10
        """)).fetchall()

    statuses = ["Pendiente", "Pendiente", "Generado", "Aprobado", "Programado",
                "Publicado", "Error", "Pendiente", "Generado", "Aprobado"]
    scores   = [95, 88, 82, 78, 74, 70, 66, 90, 85, 80]
    videos: list[dict] = []

    for i, row in enumerate(rows):
        store_tag = _STORE_TAGS.get(row.store, f"#{row.store}")
        tags = ["#ofertasperu", "#pricehunterpro", "#descuentos", store_tag, "#peru"]
        disc = int(row.disc) if row.disc else 0

        videos.append({
            "id":              str(uuid.uuid4()),
            "opportunityId":   str(row.id),
            "titulo":          row.name[:60],
            "store":           row.store,
            "category":        row.category or "General",
            "currentPrice":    row.cp,
            "originalPrice":   row.op,
            "discountPct":     disc,
            "imageUrl":        row.image_url or "",
            "url":             row.url or "",
            "guion":           _build_guion(row.name, row.store, row.cp, row.op, disc, tags),
            "hashtags":        tags,
            "plantilla":       _PLANTILLAS[i % len(_PLANTILLAS)],
            "duracion":        [15, 20, 30, 10][i % 4],
            "animacion":       ["Zoom", "Slide", "Fade"][i % 3],
            "logoPos":         "Superior" if i % 2 == 0 else "Inferior",
            "estado":          statuses[i % len(statuses)],
            "scoreIA":         scores[i % len(scores)],
            "fechaProgramada": None,
            "fechaPublicacion": None,
            "createdAt":       datetime.now(timezone.utc).isoformat(),
        })

    _save_videos(videos)
    return videos


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/videos")
def get_videos() -> dict[str, Any]:
    videos = _all_videos()
    if not videos:
        videos = _seed_videos()

    status_count: dict[str, int] = {
        "Pendiente": 0, "Generando": 0, "Generado": 0,
        "Aprobado": 0, "Programado": 0, "Publicado": 0, "Error": 0,
    }
    for v in videos:
        key = v.get("estado", "Pendiente")
        status_count[key] = status_count.get(key, 0) + 1

    return {
        "videos": videos,
        "kpis": {
            "pendientes":  status_count["Pendiente"] + status_count["Generando"],
            "generados":   status_count["Generado"],
            "programados": status_count["Programado"],
            "publicados":  status_count["Publicado"],
            "errores":     status_count["Error"],
        },
    }


@router.post("/generate")
def generate_video(body: dict = Body(...)) -> dict[str, Any]:
    opportunity_id = body.get("opportunityId", "")
    plantilla      = body.get("plantilla", "Flash Sale")
    duracion       = body.get("duracion", 15)
    animacion      = body.get("animacion", "Zoom")
    logo_pos       = body.get("logoPos", "Superior")

    # Buscar en DB si se pasa opportunity_id, si no crear mock
    titulo        = body.get("titulo", "Oferta Especial PriceHunter")
    store         = body.get("store", "falabella")
    current_price = float(body.get("currentPrice", 0))
    original_price = float(body.get("originalPrice", 0))
    disc          = int(body.get("discountPct", 0))
    image_url     = body.get("imageUrl", "")
    category      = body.get("category", "General")

    store_tag = _STORE_TAGS.get(store, f"#{store}")
    tags = ["#ofertasperu", "#pricehunterpro", "#descuentos", store_tag, "#peru"]
    guion = _build_guion(titulo, store, current_price, original_price, disc, tags)

    video: dict[str, Any] = {
        "id":               str(uuid.uuid4()),
        "opportunityId":    opportunity_id,
        "titulo":           titulo[:60],
        "store":            store,
        "category":         category,
        "currentPrice":     current_price,
        "originalPrice":    original_price,
        "discountPct":      disc,
        "imageUrl":         image_url,
        "url":              body.get("url", ""),
        "guion":            guion,
        "hashtags":         tags,
        "plantilla":        plantilla,
        "duracion":         duracion,
        "animacion":        animacion,
        "logoPos":          logo_pos,
        "estado":           "Generado",
        "scoreIA":          body.get("scoreIA", 75),
        "fechaProgramada":  None,
        "fechaPublicacion": None,
        "createdAt":        datetime.now(timezone.utc).isoformat(),
    }
    videos = _all_videos()
    videos.insert(0, video)
    _save_videos(videos)
    return video


@router.post("/approve/{video_id}")
def approve_video(video_id: str) -> dict[str, str]:
    videos = _all_videos()
    for v in videos:
        if v["id"] == video_id:
            v["estado"] = "Aprobado"
            break
    _save_videos(videos)
    return {"status": "ok", "estado": "Aprobado"}


@router.post("/schedule/{video_id}")
def schedule_video(video_id: str, body: dict = Body(...)) -> dict[str, str]:
    fecha = body.get("fecha", "")
    videos = _all_videos()
    for v in videos:
        if v["id"] == video_id:
            v["estado"] = "Programado"
            v["fechaProgramada"] = fecha
            break
    _save_videos(videos)
    return {"status": "ok", "estado": "Programado", "fecha": fecha}


@router.post("/publish/{video_id}")
def publish_video(video_id: str) -> dict[str, str]:
    videos = _all_videos()
    for v in videos:
        if v["id"] == video_id:
            v["estado"] = "Publicado"
            v["fechaPublicacion"] = datetime.now(timezone.utc).isoformat()
            break
    _save_videos(videos)
    return {"status": "ok", "estado": "Publicado"}


@router.delete("/videos/{video_id}")
def delete_video(video_id: str) -> dict[str, str]:
    videos = [v for v in _all_videos() if v["id"] != video_id]
    _save_videos(videos)
    return {"status": "ok"}


@router.post("/regenerate-guion/{video_id}")
def regenerate_guion(video_id: str) -> dict[str, str]:
    videos = _all_videos()
    for v in videos:
        if v["id"] == video_id:
            store_tag = _STORE_TAGS.get(v["store"], f"#{v['store']}")
            tags = ["#ofertasperu", "#pricehunterpro", "#descuentos", store_tag, "#peru"]
            v["guion"] = _build_guion(
                v["titulo"], v["store"],
                v["currentPrice"], v["originalPrice"],
                v["discountPct"], tags
            )
            _save_videos(videos)
            return {"guion": v["guion"]}
    return {"guion": ""}
