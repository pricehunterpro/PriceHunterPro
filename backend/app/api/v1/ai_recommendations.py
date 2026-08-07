"""Recomendaciones IA — qué comprar, qué publicar y qué ignorar.

La decisión vive en `app.services.recommendation_engine`; acá solo va la capa
HTTP + el estado de cada recomendación.

Las recomendaciones se DERIVAN del catálogo en cada corrida (no se guarda una
tabla): lo único que persiste en Redis es el estado que el administrador le puso
a una recomendación (Revisada / Ignorada / Enviada...). El `id` es estable
(`rec-{opportunity_id}`), así que ese estado sobrevive a los recálculos.

No toca ningún módulo existente: reutiliza el Motor IA (`calculate_score`),
DealService, Tendencias (agregación por categoría), Ranking IA (posición) y los
almacenes de Publicador IA / TikTok Factory para las acciones de envío.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.ai.scorer import calculate_score
from app.services.deal_service import DealService
from app.services.recommendation_engine import (
    ESTADOS,
    PRIORIDADES,
    TIPOS,
    build_recommendations,
    destacados,
    kpis,
)

router = APIRouter(prefix="/ai", tags=["ai-recommendations"])
_deal_service = DealService()

_STATE_KEY = "ai:recommendations:state"

# Recalcular puntúa todo el catálogo in_stock (~66k filas), así que se cachea.
# Mismo criterio que Tendencias IA, con TTL algo mayor porque esta vista hace
# varias llamadas seguidas (tabla + stats + detalle).
_CACHE_TTL = 120
_cache: dict[str, Any] = {"ts": 0.0, "data": None}

# Tope de recomendaciones servidas, POR TIPO. La vista es para decidir, no para
# exportar el catálogo; sin tope traería decenas de miles de filas.
# El cupo es por tipo a propósito: con un tope global único el corte se llenaba
# entero de prioridad Alta y "Revisar" quedaba en 0, justo la pregunta "¿qué debo
# revisar?" que la vista tiene que responder.
_CUPOS: dict[str, int] = {
    "Comprar y Publicar": 250,
    "Comprar": 250,
    "Enviar a Publicador IA": 200,
    "Enviar a TikTok Factory": 200,
    "Publicar": 200,
    "Revisar": 250,
    "Ignorar": 250,
}
# Dentro de cada cupo se ordena por lo que hace útil a ESE tipo.
_ORDEN_CUPO = {
    "Ignorar": lambda r: -r["discount_percent"],          # los más tentadores que igual hay que descartar
    "Enviar a TikTok Factory": lambda r: -r["viralidad"],
    "Revisar": lambda r: -r["discount_percent"],
}

_PRIORIDAD_ORDEN = {"Alta": 0, "Media": 1, "Baja": 2}


def _r():
    import redis as _redis
    from app.core.config import get_settings
    return _redis.from_url(get_settings().redis_url)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Estado persistido ────────────────────────────────────────────────────────
def _load_state() -> dict[str, dict[str, Any]]:
    try:
        raw = _r().get(_STATE_KEY)
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def _save_state(state: dict[str, dict[str, Any]]) -> None:
    try:
        _r().set(_STATE_KEY, json.dumps(state, default=str))
    except Exception:
        pass  # el estado es una comodidad: si Redis falla, la vista sigue sirviendo


def _set_status(rec_id: str, status: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    if status not in ESTADOS:
        raise HTTPException(status_code=400, detail=f"Estado inválido: {status}")
    state = _load_state()
    entry = state.get(rec_id, {})
    entry.update({"status": status, "updated_at": _now()})
    if extra:
        entry.update(extra)
    state[rec_id] = entry
    _save_state(state)
    return entry


# ── Construcción del set de recomendaciones ──────────────────────────────────
def _build_all() -> list[dict[str, Any]]:
    """Puntúa el catálogo y arma las recomendaciones. Cacheado `_CACHE_TTL`s."""
    now = time.time()
    if _cache["data"] is not None and (now - _cache["ts"]) < _CACHE_TTL:
        return _cache["data"]

    raw = _deal_service.get_deals(sort="discount", page=1, limit=50000)
    scored = [{**d, **calculate_score(d)} for d in raw["items"]]
    recs = build_recommendations(scored)

    por_tipo: dict[str, list[dict[str, Any]]] = {}
    for r in recs:
        por_tipo.setdefault(r["recommendation_type"], []).append(r)

    _orden_default = lambda r: (_PRIORIDAD_ORDEN[r["priority"]], -r["pricehunter_score"])  # noqa: E731
    data: list[dict[str, Any]] = []
    for tipo, cupo in _CUPOS.items():
        grupo = por_tipo.get(tipo, [])
        grupo.sort(key=_ORDEN_CUPO.get(tipo, _orden_default))
        data.extend(grupo[:cupo])
    data.sort(key=_orden_default)
    _cache.update(ts=now, data=data)
    return data


def _with_state(recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aplica el estado guardado sobre las recomendaciones recién calculadas."""
    state = _load_state()
    out = []
    for r in recs:
        st = state.get(r["id"])
        if st:
            r = {**r, "status": st.get("status", "Nueva"), "updated_at": st.get("updated_at", r["updated_at"])}
        out.append(r)
    return out


def _find(rec_id: str) -> dict[str, Any]:
    for r in _with_state(_build_all()):
        if r["id"] == rec_id:
            return r
    raise HTTPException(status_code=404, detail="Recomendación no encontrada")


def _filtrar(
    recs: list[dict[str, Any]],
    tipo: str | None,
    prioridad: str | None,
    store: str | None,
    category: str | None,
    min_score: int,
    estado: str | None,
    desde: str | None,
    q: str | None,
) -> list[dict[str, Any]]:
    tipos = {v for v in (tipo or "").split(",") if v}
    prioridades = {v for v in (prioridad or "").split(",") if v}
    stores = {v for v in (store or "").split(",") if v}
    categorias = {v for v in (category or "").split(",") if v}
    estados = {v for v in (estado or "").split(",") if v}
    texto = (q or "").strip().lower()

    out = []
    for r in recs:
        if tipos and r["recommendation_type"] not in tipos:
            continue
        if prioridades and r["priority"] not in prioridades:
            continue
        if stores and r["store"] not in stores:
            continue
        if categorias and r["category"] not in categorias:
            continue
        if min_score and r["pricehunter_score"] < min_score:
            continue
        if estados and r["status"] not in estados:
            continue
        if desde and r["created_at"] and r["created_at"] < desde:
            continue
        if texto:
            heno = f"{r['product_name']} {r['brand']} {r['category']} {r['store']}".lower()
            if texto not in heno:
                continue
        out.append(r)
    return out


def _ordenar(recs: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    if sort == "score":
        return sorted(recs, key=lambda r: -r["pricehunter_score"])
    if sort == "roi":
        return sorted(recs, key=lambda r: -r["estimated_margin"])
    if sort == "discount":
        return sorted(recs, key=lambda r: -r["discount_percent"])
    if sort == "viral":
        return sorted(recs, key=lambda r: -r["viralidad"])
    if sort == "price_asc":
        return sorted(recs, key=lambda r: r["current_price"])
    # por defecto: prioridad y luego score (el orden en que conviene atenderlas)
    return sorted(recs, key=lambda r: (_PRIORIDAD_ORDEN[r["priority"]], -r["pricehunter_score"]))


# ── Endpoints ────────────────────────────────────────────────────────────────
# OJO: /recommendations/stats va ANTES que /recommendations/{rec_id}, si no
# FastAPI resolvería "stats" como un id.

@router.get("/recommendations/stats")
def recommendations_stats(
    tipo: str | None = Query(default=None),
    prioridad: str | None = Query(default=None),
    store: str | None = Query(default=None),
    category: str | None = Query(default=None),
    min_score: int = Query(default=0, ge=0, le=100),
    estado: str | None = Query(default=None),
    desde: str | None = Query(default=None, description="ISO date; filtra por created_at"),
    q: str | None = Query(default=None),
) -> dict[str, Any]:
    """KPIs + respuestas a las 5 preguntas de la vista, con los mismos filtros."""
    recs = _filtrar(
        _with_state(_build_all()), tipo, prioridad, store, category, min_score, estado, desde, q,
    )
    return {"kpis": kpis(recs), "destacados": destacados(recs)}


@router.get("/recommendations")
def list_recommendations(
    tipo: str | None = Query(default=None, description="Coma-separado: Comprar,Publicar,…"),
    prioridad: str | None = Query(default=None, description="Alta,Media,Baja"),
    store: str | None = Query(default=None),
    category: str | None = Query(default=None),
    min_score: int = Query(default=0, ge=0, le=100),
    estado: str | None = Query(default=None),
    desde: str | None = Query(default=None),
    q: str | None = Query(default=None),
    sort: str = Query(default="priority", description="priority|score|roi|discount|viral|price_asc"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    todas = _with_state(_build_all())
    recs = _filtrar(todas, tipo, prioridad, store, category, min_score, estado, desde, q)
    recs = _ordenar(recs, sort)

    total = len(recs)
    start = (page - 1) * limit
    return {
        "items": recs[start: start + limit],
        "total": total,
        "page": page,
        "limit": limit,
        "kpis": kpis(recs),
        "destacados": destacados(recs),
        "filters": {
            "tipos": TIPOS,
            "prioridades": PRIORIDADES,
            "estados": ESTADOS,
            "stores": sorted({r["store"] for r in todas if r["store"]}),
            "categories": sorted({r["category"] for r in todas if r["category"]}),
        },
    }


@router.get("/recommendations/{rec_id}")
def get_recommendation(rec_id: str) -> dict[str, Any]:
    return {"item": _find(rec_id)}


@router.post("/recommendations/{rec_id}/mark-reviewed")
def mark_reviewed(rec_id: str) -> dict[str, Any]:
    rec = _find(rec_id)
    _set_status(rec_id, "Revisada")
    return {"status": "ok", "estado": "Revisada", "item": {**rec, "status": "Revisada"}}


@router.post("/recommendations/{rec_id}/ignore")
def ignore(rec_id: str) -> dict[str, Any]:
    rec = _find(rec_id)
    _set_status(rec_id, "Ignorada")
    return {"status": "ok", "estado": "Ignorada", "item": {**rec, "status": "Ignorada"}}


@router.post("/recommendations/{rec_id}/send-to-publisher")
def send_to_publisher(rec_id: str) -> dict[str, Any]:
    """Crea un item real en Publicador IA reutilizando sus propios generadores."""
    import uuid

    from app.api.v1.publicador import (
        _all_items, _generar_contenido, _hashtags, _save_items,
    )

    rec = _find(rec_id)
    disc = int(rec["discount_percent"])
    canales = ["Telegram"]
    contenido = _generar_contenido(
        "Telegram", rec["product_name"], rec["store"], rec["category"],
        rec["current_price"], rec["original_price"], disc, rec["url"],
    )
    item = {
        "id": str(uuid.uuid4()),
        "opportunityId": rec["opportunity_id"],
        "titulo": rec["product_name"][:70],
        "store": rec["store"],
        "category": rec["category"],
        "currentPrice": rec["current_price"],
        "originalPrice": rec["original_price"],
        "discountPct": disc,
        "imageUrl": rec["image_url"],
        "url": rec["url"],
        "canalesSeleccionados": canales,
        "contenido": contenido,
        "hashtags": _hashtags(rec["store"], rec["category"], disc),
        "scoreIA": rec["pricehunter_score"],
        "estado": "Generado",
        "fechaProgramada": None,
        "fechaPublicacion": None,
        "generadoAt": _now(),
        "createdAt": _now(),
        "origen": "Recomendaciones IA",
    }
    items = _all_items()
    items.insert(0, item)
    _save_items(items)

    _set_status(rec_id, "Enviada a Publicador", {"publicador_item_id": item["id"]})
    return {"status": "ok", "estado": "Enviada a Publicador", "publicadorItemId": item["id"]}


@router.post("/recommendations/{rec_id}/send-to-tiktok")
def send_to_tiktok(rec_id: str) -> dict[str, Any]:
    """Crea un video en TikTok Factory reutilizando su generador de guion."""
    import uuid

    from app.api.v1.tiktok import _STORE_TAGS, _all_videos, _build_guion, _save_videos

    rec = _find(rec_id)
    disc = int(rec["discount_percent"])
    tags = [
        "#ofertasperu", "#pricehunterpro", "#descuentos",
        _STORE_TAGS.get(rec["store"], f"#{rec['store']}"), "#peru",
    ]
    video = {
        "id": str(uuid.uuid4()),
        "opportunityId": rec["opportunity_id"],
        "titulo": rec["product_name"][:60],
        "store": rec["store"],
        "category": rec["category"],
        "currentPrice": rec["current_price"],
        "originalPrice": rec["original_price"],
        "discountPct": disc,
        "imageUrl": rec["image_url"],
        "url": rec["url"],
        "guion": _build_guion(
            rec["product_name"], rec["store"], rec["current_price"],
            rec["original_price"], disc, tags,
        ),
        "hashtags": tags,
        "plantilla": "Top Oferta del Día",
        "duracion": 15,
        "animacion": "Zoom",
        "logoPos": "Superior",
        "estado": "Generado",
        "scoreIA": rec["pricehunter_score"],
        "fechaProgramada": None,
        "fechaPublicacion": None,
        "createdAt": _now(),
        "origen": "Recomendaciones IA",
    }
    videos = _all_videos()
    videos.insert(0, video)
    _save_videos(videos)

    _set_status(rec_id, "Enviada a TikTok", {"tiktok_video_id": video["id"]})
    return {"status": "ok", "estado": "Enviada a TikTok", "tiktokVideoId": video["id"]}


@router.post("/recommendations/{rec_id}/add-to-portfolio")
def add_to_portfolio(rec_id: str) -> dict[str, Any]:
    """Agrega la recomendación al Portafolio (BI) como compra registrada."""
    from app.api.v1.bi_portfolio import create as portfolio_create

    rec = _find(rec_id)
    res = portfolio_create({
        "opportunity_id": rec["opportunity_id"],
        "product_name": rec["product_name"],
        "store": rec["store"],
        "category": rec["category"],
        "quantity": 1,
        "purchase_price": rec["current_price"],
        "suggested_sale_price": rec["original_price"],
        "status": "Comprado",
        "image_url": rec["image_url"],
        "notes": f"Origen: Recomendaciones IA — {rec['reason']}",
    })
    _set_status(rec_id, "Revisada", {"portfolio_item_id": res["item"]["id"]})
    return {"status": "ok", "portfolioItemId": res["item"]["id"]}
