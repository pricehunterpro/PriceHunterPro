"""Analytics — vista ejecutiva de rendimiento de PriceHunter Pro.

Consume servicios/agregaciones ya existentes (no duplica lógica):
- Ofertas/score: `DealService` + `calculate_score` (vía helpers de `ai_trends`).
- Publicaciones: items del Publicador IA (Redis).
- Videos: TikTok Factory (Redis).
- Series temporales: `price_history`.

Clicks/CTR: no hay tracking real todavía → estimación determinista, claramente
marcada como estimada y lista para reemplazar por métricas reales.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.v1.ai_trends import _agg, _parse_list, _scored, _temporal
from app.services.deal_service import _engine

router = APIRouter(prefix="/bi/analytics", tags=["bi-analytics"])

_CHANNELS = ["Telegram", "Facebook", "Instagram", "TikTok"]


def _pub_items() -> list[dict]:
    try:
        from app.api.v1.publicador import _all_items
        return _all_items()
    except Exception:
        return []


def _tiktok_videos() -> list[dict]:
    try:
        from app.api.v1.tiktok import _all_videos
        return _all_videos()
    except Exception:
        return []


# ── Resumen / KPIs ───────────────────────────────────────────────────────────
@router.get("/summary")
def summary(
    store:     str | None = Query(default=None),
    category:  str | None = Query(default=None),
    brand:     str | None = Query(default=None),
    min_score: int        = Query(default=0, ge=0, le=100),
) -> dict[str, Any]:
    items = _scored(_parse_list(store), _parse_list(category), brand, min_score)
    n = len(items)

    oportunidades = n
    gangas  = sum(1 for d in items if d["discountPct"] >= 40 and d["currentPrice"] >= 50)
    alertas = sum(1 for d in items if d.get("belowMarket"))
    score_prom = round(sum(d["score"] for d in items) / n, 1) if n else 0

    pubs = _pub_items()
    publicaciones = sum(1 for p in pubs if p.get("estado") == "Publicado")
    videos = len(_tiktok_videos())

    # ── Clicks / CTR estimados (mock determinista — reemplazar por tracking real) ──
    impresiones_est = publicaciones * 3000 + videos * 8000
    clicks_est = publicaciones * 150 + videos * 400
    ctr_est = round(clicks_est / impresiones_est * 100, 2) if impresiones_est else 0.0

    return {
        "kpis": {
            "oportunidadesDetectadas":  oportunidades,
            "gangasDetectadas":         gangas,
            "alertasGeneradas":         alertas,
            "publicacionesRealizadas":  publicaciones,
            "videosTiktokGenerados":    videos,
            "clicksEstimados":          clicks_est,
            "ctrEstimado":              ctr_est,
            "scorePromedio":            score_prom,
        },
        "estimated": ["clicksEstimados", "ctrEstimado"],
    }


# ── Ofertas por día (real, price_history) ────────────────────────────────────
@router.get("/offers-by-day")
def offers_by_day(
    store:  str | None = Query(default=None),
    period: str        = Query(default="30d", description="24h|7d|30d|90d"),
) -> dict[str, Any]:
    return _temporal(period, _parse_list(store))


# ── Ofertas por tienda ───────────────────────────────────────────────────────
@router.get("/offers-by-store")
def offers_by_store(
    store=Query(None), category=Query(None), brand=Query(None), min_score: int = Query(0),
) -> dict[str, Any]:
    items = _scored(_parse_list(store), _parse_list(category), brand, min_score)
    rows = sorted(_agg(items, "store"), key=lambda r: r["ofertas"], reverse=True)
    return {"items": rows, "total": len(rows)}


# ── Ofertas por categoría (+ top categorías) ─────────────────────────────────
@router.get("/offers-by-category")
def offers_by_category(
    store=Query(None), category=Query(None), brand=Query(None), min_score: int = Query(0),
    limit: int = Query(12, ge=1, le=50),
) -> dict[str, Any]:
    items = _scored(_parse_list(store), _parse_list(category), brand, min_score)
    rows = sorted(_agg(items, "category"), key=lambda r: r["ofertas"], reverse=True)
    return {"items": rows[:limit], "total": len(rows)}


# ── Publicaciones por canal (Publicador IA) ──────────────────────────────────
@router.get("/publications-by-channel")
def publications_by_channel(channel: str | None = Query(default=None)) -> dict[str, Any]:
    pubs = _pub_items()
    rows = []
    for canal in _CHANNELS:
        targeting = [p for p in pubs if canal in (p.get("canalesSeleccionados") or [])]
        rows.append({
            "canal":       canal,
            "total":       len(targeting),
            "publicados":  sum(1 for p in targeting if p.get("estado") == "Publicado"),
            "programados": sum(1 for p in targeting if p.get("estado") == "Programado"),
        })
    if channel:
        rows = [r for r in rows if r["canal"] == channel]
    return {"items": rows}


# ── Evolución del Score IA (derivado de price_history) ───────────────────────
@router.get("/score-evolution")
def score_evolution(
    store:  str | None = Query(default=None),
    period: str        = Query(default="30d"),
) -> dict[str, Any]:
    """Score IA aproximado por período. No hay histórico de score almacenado,
    así que se deriva del descuento promedio real por bucket (proxy consistente
    con el scorer). Listo para reemplazar por score histórico real."""
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    cfg = {
        "24h": ("hour", "24 hours", "HH24:00"),
        "7d":  ("day",  "7 days",   "DD/MM"),
        "30d": ("day",  "30 days",  "DD/MM"),
        "90d": ("week", "90 days",  "DD/MM"),
    }
    unit, interval, fmt = cfg.get(period, cfg["30d"])
    stores = _parse_list(store)

    store_filter, params = "", {}
    if stores:
        store_filter = "AND ph.store_product_id IN (SELECT id FROM store_products WHERE store = ANY(:stores))"
        params["stores"] = stores

    sql = text(f"""
        SELECT to_char(date_trunc('{unit}', ph.scraped_at), '{fmt}') AS bucket,
               date_trunc('{unit}', ph.scraped_at)                   AS ord,
               AVG(CASE WHEN ph.original_price > 0 AND ph.original_price >= ph.price
                        THEN (ph.original_price - ph.price) / ph.original_price * 100
                        ELSE 0 END) AS desc_prom
        FROM price_history ph
        WHERE ph.scraped_at >= NOW() - INTERVAL '{interval}' AND ph.price > 0 {store_filter}
        GROUP BY 1, 2 ORDER BY 2
    """)

    labels, scores = [], []
    try:
        with Session(_engine) as s:
            for row in s.execute(sql, params).all():
                d = float(row[2] or 0)
                # proxy de score: base 45 + peso del descuento (cap 100)
                proxy = min(100.0, 45 + d * 0.55)
                labels.append(row[0])
                scores.append(round(proxy, 1))
    except Exception:
        pass
    return {"period": period, "labels": labels, "scores": scores, "derived": True}
