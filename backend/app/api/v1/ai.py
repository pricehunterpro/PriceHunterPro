from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Query

from app.ai.scorer import calculate_score
from app.services.deal_service import DealService

router = APIRouter(prefix="/ai", tags=["ai"])
_deal_service = DealService()


@router.get("/score-opportunities")
def score_opportunities(
    store:         str | None = Query(default=None),
    category:      str | None = Query(default=None),
    clasificacion: str | None = Query(default=None, description="Ganga Extrema | Excelente Oferta | Buena Oferta | Oferta Normal"),
    min_score:     int        = Query(default=0,  ge=0, le=100),
    min_discount:  int        = Query(default=0,  ge=0),
    sort:          str        = Query(default="score"),
    page:          int        = Query(default=1,  ge=1),
    limit:         int        = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """
    Devuelve oportunidades enriquecidas con el PriceHunter Score (0-100),
    clasificación, recomendación y explicación del cálculo.
    """
    stores     = [v for v in (store    or "").split(",") if v] or None
    categories = [v for v in (category or "").split(",") if v] or None

    raw = _deal_service.get_deals(
        stores=stores,
        categories=categories,
        sort="discount",
        min_discount=min_discount,
        page=1,
        limit=5000,
    )
    items: list[dict[str, Any]] = raw["items"]

    # Score every item
    scored: list[dict[str, Any]] = []
    for deal in items:
        ai = calculate_score(deal)
        scored.append({**deal, **ai})

    # Filters post-score
    if min_score > 0:
        scored = [d for d in scored if d["score"] >= min_score]
    if clasificacion:
        scored = [d for d in scored if d["clasificacion"] == clasificacion]

    # Sort
    if sort == "score":
        scored.sort(key=lambda d: d["score"], reverse=True)
    elif sort == "discount":
        scored.sort(key=lambda d: d["discountPct"], reverse=True)
    elif sort == "margin":
        scored.sort(key=lambda d: d["marginPct"], reverse=True)
    elif sort == "price_asc":
        scored.sort(key=lambda d: d["currentPrice"])
    elif sort == "price_desc":
        scored.sort(key=lambda d: d["currentPrice"], reverse=True)

    # KPIs
    total = len(scored)
    extremas    = sum(1 for d in scored if d["clasificacion"] == "Ganga Extrema")
    excelentes  = sum(1 for d in scored if d["clasificacion"] == "Excelente Oferta")
    buenas      = sum(1 for d in scored if d["clasificacion"] == "Buena Oferta")
    normales    = sum(1 for d in scored if d["clasificacion"] == "Oferta Normal")
    avg_score   = round(sum(d["score"] for d in scored) / total, 1) if total else 0

    # Paginate
    start = (page - 1) * limit
    page_items = scored[start: start + limit]

    all_raw = _deal_service.get_deals(page=1, limit=5000)
    all_items = all_raw["items"]

    return {
        "items": page_items,
        "total": total,
        "kpis": {
            "totalAnalizadas": total,
            "gangasExtremas":  extremas,
            "excelentesOfertas": excelentes,
            "buenasOfertas":   buenas,
            "ofertasNormales": normales,
            "promedioScore":   avg_score,
        },
        "filters": {
            "stores":     sorted({i["store"]    for i in all_items}),
            "categories": sorted({i["category"] for i in all_items}),
        },
    }


@router.get("/ranking")
def ranking(
    store:    str | None = Query(default=None),
    category: str | None = Query(default=None),
    sort:     str        = Query(default="score", description="score|margin|discount|price|store|category"),
    page:     int        = Query(default=1,  ge=1),
    limit:    int        = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Ranking de las mejores oportunidades según el PriceHunter Score.
    Reutiliza `calculate_score` (Motor IA) — no duplica el cálculo."""
    stores     = [v for v in (store    or "").split(",") if v] or None
    categories = [v for v in (category or "").split(",") if v] or None

    raw = _deal_service.get_deals(
        stores=stores, categories=categories, sort="discount",
        min_discount=0, page=1, limit=5000,
    )
    items: list[dict[str, Any]] = raw["items"]

    scored: list[dict[str, Any]] = []
    for deal in items:
        ai = calculate_score(deal)
        scored.append({
            "id":             deal["id"],
            "name":           deal["name"],
            "brand":          deal.get("brand", ""),
            "store":          deal["store"],
            "category":       deal["category"],
            "currentPrice":   deal["currentPrice"],
            "originalPrice":  deal["originalPrice"],
            "avgMarketPrice": deal.get("avgMarketPrice", 0),
            "discountPct":    deal["discountPct"],
            "marginPct":      deal["marginPct"],
            "mktDiffPct":     deal.get("mktDiffPct", 0),
            "belowMarket":    deal.get("belowMarket", False),
            "inStock":        deal.get("inStock", True),
            "imageUrl":       deal.get("imageUrl", ""),
            "url":            deal.get("url", ""),
            **ai,
        })

    # ── Orden ──
    if sort == "margin":
        scored.sort(key=lambda d: d["marginPct"], reverse=True)
    elif sort == "discount":
        scored.sort(key=lambda d: d["discountPct"], reverse=True)
    elif sort == "price":  # precio mínimo (más barato primero)
        scored.sort(key=lambda d: d["currentPrice"])
    elif sort == "store":
        scored.sort(key=lambda d: (d["store"], -d["score"]))
    elif sort == "category":
        scored.sort(key=lambda d: (d["category"], -d["score"]))
    else:  # score
        scored.sort(key=lambda d: d["score"], reverse=True)

    total = len(scored)
    for i, d in enumerate(scored):
        d["posicion"] = i + 1

    # ── KPIs (los "top" siempre por score) ──
    by_score = sorted(scored, key=lambda d: d["score"], reverse=True)
    top10 = by_score[:10]
    avg_top10 = round(sum(d["score"] for d in top10) / len(top10), 1) if top10 else 0

    store_scores: dict[str, list[int]] = defaultdict(list)
    for d in scored:
        store_scores[d["store"]].append(d["score"])
    mejor_tienda, best_avg = "", -1.0
    for st, scs in store_scores.items():
        if len(scs) >= 5:
            avg = sum(scs) / len(scs)
            if avg > best_avg:
                best_avg, mejor_tienda = avg, st
    if not mejor_tienda and by_score:
        mejor_tienda = by_score[0]["store"]

    start = (page - 1) * limit
    page_items = scored[start: start + limit]

    all_items = _deal_service.get_deals(page=1, limit=5000)["items"]

    return {
        "items": page_items,
        "total": total,
        "kpis": {
            "topOportunidades":    total,
            "scorePromedioTop10":  avg_top10,
            "mayorMargen":         round(max((d["marginPct"] for d in scored), default=0), 1),
            "mayorDescuento":      round(max((d["discountPct"] for d in scored), default=0), 1),
            "mejorTienda":         mejor_tienda,
            "mejorTiendaScore":    round(best_avg, 1) if best_avg >= 0 else 0,
        },
        "filters": {
            "stores":     sorted({i["store"]    for i in all_items}),
            "categories": sorted({i["category"] for i in all_items}),
        },
    }
