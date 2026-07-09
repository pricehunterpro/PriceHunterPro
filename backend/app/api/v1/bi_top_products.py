"""Top Productos — ranking inteligente de productos con mejor desempeño.

Combina, sin duplicar lógica:
- PriceHunter Score (Motor IA, vía `_scored`).
- ROI de reventa (modelo de `bi_profitability`).
- Frecuencia detectada (nº de listados del mismo producto) → popularidad.

Clicks estimados: mock determinista (no hay tracking real todavía).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Query

from app.api.v1.ai_trends import _parse_list, _scored
from app.api.v1.bi_profitability import _profit_row

router = APIRouter(prefix="/bi/top-products", tags=["bi-top-products"])

_PERIOD_DAYS = {"hoy": 1, "7d": 7, "30d": 30, "90d": 90}


def _within_period(scraped_at: str, days: int) -> bool:
    if not scraped_at:
        return True
    try:
        dt = datetime.fromisoformat(scraped_at.replace("Z", "+00:00"))
        return dt >= datetime.now(timezone.utc) - timedelta(days=days)
    except Exception:
        return True


def _rows(store, category, brand, min_score, period) -> list[dict[str, Any]]:
    items = _scored(_parse_list(store), _parse_list(category), brand, min_score)

    days = _PERIOD_DAYS.get(period, 90)
    if period in _PERIOD_DAYS and period != "90d":
        items = [d for d in items if _within_period(d.get("scrapedAt", ""), days)]

    # Frecuencia detectada por nombre normalizado
    freq: Counter = Counter((d.get("name") or "").strip().lower() for d in items)

    rows = []
    for d in items:
        pr = _profit_row(d)
        roi = pr["roi"] if pr else 0.0
        sugerido = pr["precioSugerido"] if pr else d.get("currentPrice", 0)
        score = int(d.get("score", 0) or 0)
        disc = float(d.get("discountPct", 0) or 0)
        frecuencia = freq.get((d.get("name") or "").strip().lower(), 1)

        # Clicks estimados (mock determinista) y popularidad (índice 0-100)
        clicks = round(score * 10 + disc * 5 + frecuencia * 40)
        popularidad = round(min(100.0, 0.6 * score + 4 * min(frecuencia, 8) + 0.12 * min(disc, 80)), 1)

        rows.append({
            "id":             d.get("id"),
            "name":           d.get("name"),
            "store":          d.get("store"),
            "category":       d.get("category"),
            "imageUrl":       d.get("imageUrl", ""),
            "url":            d.get("url", ""),
            "currentPrice":   d.get("currentPrice", 0),
            "avgMarketPrice": d.get("avgMarketPrice", 0),
            "precioSugerido": sugerido,
            "discountPct":    round(disc, 1),
            "marginPct":      round(float(d.get("marginPct", 0) or 0), 1),
            "roi":            roi,
            "score":          score,
            "clasificacion":  d.get("clasificacion", ""),
            "clasificacionEmoji": d.get("clasificacionEmoji", ""),
            "recomendacion":  d.get("recomendacion", ""),
            "clicksEstimados": clicks,
            "popularidad":    popularidad,
            "frecuencia":     frecuencia,
        })
    return rows


_SORT_KEYS = {
    "score": "score", "roi": "roi", "margen": "marginPct", "descuento": "discountPct",
    "clicks": "clicksEstimados", "popularidad": "popularidad", "frecuencia": "frecuencia",
}


@router.get("")
def top_products(
    store=Query(None), category=Query(None), brand=Query(None),
    min_score: int = Query(0), period: str = Query("30d", description="hoy|7d|30d|90d"),
    sort: str = Query("score"),
    page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    rows = _rows(store, category, brand, min_score, period)
    key = _SORT_KEYS.get(sort, "score")
    rows.sort(key=lambda r: r[key], reverse=True)

    total = len(rows)
    for i, r in enumerate(rows):
        r["ranking"] = i + 1

    start = (page - 1) * limit
    return {"items": rows[start: start + limit], "total": total}


@router.get("/summary")
def summary(
    store=Query(None), category=Query(None), brand=Query(None),
    min_score: int = Query(0), period: str = Query("30d"),
) -> dict[str, Any]:
    rows = _rows(store, category, brand, min_score, period)
    if not rows:
        return {"kpis": {
            "productoTopDelDia": "—", "mejorScore": 0, "mayorRoi": 0,
            "mayorDescuento": 0, "categoriaDominante": "—",
        }}

    top = max(rows, key=lambda r: r["score"])
    cat_counts: dict[str, int] = defaultdict(int)
    for r in rows:
        if r["category"]:
            cat_counts[r["category"]] += 1
    cat_dom = max(cat_counts.items(), key=lambda kv: kv[1])[0] if cat_counts else "—"

    return {
        "kpis": {
            "productoTopDelDia":  top["name"],
            "productoTopScore":   top["score"],
            "productoTopStore":   top["store"],
            "mejorScore":         max(r["score"] for r in rows),
            "mayorRoi":           round(max(r["roi"] for r in rows), 1),
            "mayorDescuento":     round(max(r["discountPct"] for r in rows), 1),
            "categoriaDominante": cat_dom,
        },
    }
