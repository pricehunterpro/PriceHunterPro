"""Tendencias IA — Centro de Inteligencia del Mercado.

Reutiliza el dataset puntuado por el Motor IA (`calculate_score` + `DealService`)
y la tabla `price_history` para las series temporales. No duplica el cálculo del
score. Pensado para alimentar después Recomendaciones IA, Analytics y el
Dashboard Ejecutivo (agregaciones compartidas por estos endpoints).
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Query

from app.ai.scorer import calculate_score
from app.services.deal_service import DealService, _engine

router = APIRouter(prefix="/ai", tags=["ai-trends"])
_deal_service = DealService()

# Caché corta del dataset puntuado: las 6 secciones consultan casi a la vez,
# así el scoring de ~todo el catálogo in_stock se hace una sola vez por
# combinación de filtros.
_CACHE_TTL = 60
_cache: dict[str, Any] = {"key": None, "ts": 0.0, "data": None}


def _scored(stores, categories, brand, min_score) -> list[dict[str, Any]]:
    key = f"{stores}|{categories}|{brand}|{min_score}"
    now = time.time()
    if _cache["key"] == key and (now - _cache["ts"]) < _CACHE_TTL and _cache["data"] is not None:
        return _cache["data"]

    raw = _deal_service.get_deals(
        stores=stores, categories=categories, sort="discount",
        min_discount=0, page=1, limit=50000,
    )
    brand_l = (brand or "").lower()
    out: list[dict[str, Any]] = []
    for deal in raw["items"]:
        if brand_l and (deal.get("brand", "") or "").lower() != brand_l:
            continue
        ai = calculate_score(deal)
        d = {**deal, **ai}
        if min_score and d["score"] < min_score:
            continue
        out.append(d)

    _cache.update(key=key, ts=now, data=out)
    return out


def _parse_list(v: str | None) -> list[str] | None:
    return [x for x in (v or "").split(",") if x] or None


def _agg(items: list[dict], field: str) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for d in items:
        k = (d.get(field) or "").strip()
        if k:
            groups[k].append(d)
    rows = []
    for k, ds in groups.items():
        n = len(ds)
        rows.append({
            field:                k,
            "ofertas":            n,
            "descuentoPromedio":  round(sum(x["discountPct"] for x in ds) / n, 1),
            "scorePromedio":      round(sum(x["score"] for x in ds) / n, 1),
            "margenPromedio":     round(sum(x["marginPct"] for x in ds) / n, 1),
            "descuentosAltos":    sum(1 for x in ds if x["discountPct"] >= 60),
        })
    return rows


# ── KPIs + filtros + serie temporal ─────────────────────────────────────────
@router.get("/trends")
def trends(
    store:     str | None = Query(default=None),
    brand:     str | None = Query(default=None),
    category:  str | None = Query(default=None),
    min_score: int        = Query(default=0, ge=0, le=100),
    period:    str        = Query(default="7d", description="24h|7d|30d|90d"),
) -> dict[str, Any]:
    items = _scored(_parse_list(store), _parse_list(category), brand, min_score)
    n = len(items) or 1

    kpis = {
        "productosMonitoreados": len(items),
        "categoriasActivas":     len({d["category"] for d in items if d.get("category")}),
        "marcasActivas":         len({d["brand"] for d in items if d.get("brand")}),
        "tiendasMonitoreadas":   len({d["store"] for d in items if d.get("store")}),
        "descuentoPromedio":     round(sum(d["discountPct"] for d in items) / n, 1),
        "margenPromedio":        round(sum(d["marginPct"] for d in items) / n, 1),
        "scorePromedio":         round(sum(d["score"] for d in items) / n, 1),
    }

    all_items = _deal_service.get_deals(page=1, limit=50000)["items"]
    filters = {
        "stores":     sorted({i["store"] for i in all_items if i.get("store")}),
        "categories": sorted({i["category"] for i in all_items if i.get("category")}),
        "brands":     sorted({i["brand"] for i in all_items if i.get("brand")}),
    }

    return {"kpis": kpis, "filters": filters, "temporal": _temporal(period, _parse_list(store))}


def _temporal(period: str, stores: list[str] | None) -> dict[str, Any]:
    """Serie temporal desde price_history (cantidad de ofertas + descuento prom)."""
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    cfg = {
        "24h": ("hour", "24 hours",  "HH24:00"),
        "7d":  ("day",  "7 days",    "DD/MM"),
        "30d": ("day",  "30 days",   "DD/MM"),
        "90d": ("week", "90 days",   "DD/MM"),
    }
    unit, interval, fmt = cfg.get(period, cfg["7d"])

    store_filter = ""
    params: dict[str, Any] = {}
    if stores:
        store_filter = """
            AND ph.store_product_id IN (
                SELECT id FROM store_products WHERE store = ANY(:stores)
            )
        """
        params["stores"] = stores

    sql = text(f"""
        SELECT to_char(date_trunc('{unit}', ph.scraped_at), '{fmt}') AS bucket,
               date_trunc('{unit}', ph.scraped_at)                   AS ord,
               COUNT(*)                                               AS ofertas,
               AVG(CASE WHEN ph.original_price > 0 AND ph.original_price >= ph.price
                        THEN (ph.original_price - ph.price) / ph.original_price * 100
                        ELSE 0 END)                                   AS desc_prom
        FROM price_history ph
        WHERE ph.scraped_at >= NOW() - INTERVAL '{interval}'
          AND ph.price > 0
          {store_filter}
        GROUP BY 1, 2
        ORDER BY 2
    """)

    labels, ofertas, descuentos = [], [], []
    try:
        with Session(_engine) as s:
            for row in s.execute(sql, params).all():
                labels.append(row[0])
                ofertas.append(int(row[2]))
                descuentos.append(round(float(row[3] or 0), 1))
    except Exception:
        pass
    return {"period": period, "labels": labels, "ofertas": ofertas, "descuentos": descuentos}


# ── Secciones ────────────────────────────────────────────────────────────────
@router.get("/trends/categories")
def trends_categories(store=Query(None), brand=Query(None), category=Query(None), min_score: int = Query(0)) -> dict[str, Any]:
    items = _scored(_parse_list(store), _parse_list(category), brand, min_score)
    rows = sorted(_agg(items, "category"), key=lambda r: r["ofertas"], reverse=True)
    return {"items": rows, "total": len(rows)}


@router.get("/trends/stores")
def trends_stores(store=Query(None), brand=Query(None), category=Query(None), min_score: int = Query(0)) -> dict[str, Any]:
    items = _scored(_parse_list(store), _parse_list(category), brand, min_score)
    rows = sorted(_agg(items, "store"), key=lambda r: r["ofertas"], reverse=True)
    return {"items": rows, "total": len(rows)}


@router.get("/trends/brands")
def trends_brands(store=Query(None), brand=Query(None), category=Query(None), min_score: int = Query(0), limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    items = _scored(_parse_list(store), _parse_list(category), brand, min_score)
    rows = _agg(items, "brand")
    for r in rows:
        r["productos"] = r.pop("ofertas")
    rows.sort(key=lambda r: r["productos"], reverse=True)
    return {"items": rows[:limit], "total": len(rows)}


@router.get("/trends/products")
def trends_products(store=Query(None), brand=Query(None), category=Query(None), min_score: int = Query(0), limit: int = Query(25, ge=1, le=100)) -> dict[str, Any]:
    """Productos más repetidos (mismo producto detectado en varias tiendas/veces)."""
    items = _scored(_parse_list(store), _parse_list(category), brand, min_score)
    groups: dict[str, list[dict]] = defaultdict(list)
    for d in items:
        key = (d.get("name") or "").strip().lower()
        if key:
            groups[key].append(d)

    rows = []
    for _, ds in groups.items():
        prices = [x["currentPrice"] for x in ds if x["currentPrice"] > 0]
        if not prices:
            continue
        n = len(ds)
        rows.append({
            "name":           ds[0]["name"],
            "veces":          n,
            "tiendas":        sorted({x["store"] for x in ds}),
            "precioMin":      round(min(prices), 2),
            "precioMax":      round(max(prices), 2),
            "precioProm":     round(sum(prices) / len(prices), 2),
            "scorePromedio":  round(sum(x["score"] for x in ds) / n, 1),
            "imageUrl":       ds[0].get("imageUrl", ""),
        })
    rows.sort(key=lambda r: (r["veces"], r["scorePromedio"]), reverse=True)
    return {"items": rows[:limit], "total": len(rows)}


# ── Insights IA (auto-generados) ─────────────────────────────────────────────
@router.get("/trends/insights")
def trends_insights(store=Query(None), brand=Query(None), category=Query(None), min_score: int = Query(0)) -> dict[str, Any]:
    items = _scored(_parse_list(store), _parse_list(category), brand, min_score)
    insights: list[dict[str, str]] = []
    if not items:
        return {"items": insights}

    cats  = _agg(items, "category")
    stores_agg = _agg(items, "store")
    brands = [b for b in _agg(items, "brand")]

    def _cap(s: str) -> str:
        return s[:1].upper() + s[1:] if s else s

    # 1. Categoría con mayor margen
    if cats:
        c = max(cats, key=lambda r: r["margenPromedio"])
        insights.append({"tipo": "margen", "icon": "📈",
            "titulo": f"La categoría {_cap(c['category'])} presenta el mayor margen promedio ({c['margenPromedio']:.0f}%)."})
    # 2. Tienda con más ofertas
    if stores_agg:
        s = max(stores_agg, key=lambda r: r["ofertas"])
        insights.append({"tipo": "tienda", "icon": "🏪",
            "titulo": f"{_cap(s['store'])} está lanzando más ofertas: {s['ofertas']:,} productos detectados."})
    # 3. Marca líder en Score IA
    strong_brands = [b for b in brands if b["ofertas"] >= 3]
    if strong_brands:
        b = max(strong_brands, key=lambda r: r["scorePromedio"])
        insights.append({"tipo": "marca", "icon": "🏆",
            "titulo": f"{_cap(b['brand'])} lidera el Score IA con {b['scorePromedio']} de promedio."})
    # 4. Categoría con más descuentos >60%
    if cats:
        c = max(cats, key=lambda r: r["descuentosAltos"])
        if c["descuentosAltos"] > 0:
            insights.append({"tipo": "descuento", "icon": "🔥",
                "titulo": f"{_cap(c['category'])} registra la mayor cantidad de descuentos superiores al 60% ({c['descuentosAltos']} productos)."})
    # 5. Mejor tienda por score
    strong_stores = [s for s in stores_agg if s["ofertas"] >= 5]
    if strong_stores:
        s = max(strong_stores, key=lambda r: r["scorePromedio"])
        insights.append({"tipo": "score", "icon": "⭐",
            "titulo": f"{_cap(s['store'])} tiene el mejor Score IA promedio entre tiendas ({s['scorePromedio']})."})
    # 6. Categoría más activa
    if cats:
        c = max(cats, key=lambda r: r["ofertas"])
        insights.append({"tipo": "actividad", "icon": "📊",
            "titulo": f"{_cap(c['category'])} es la categoría más activa con {c['ofertas']:,} ofertas."})
    # 7. Crecimiento semanal por tienda (price_history)
    growth = _store_growth()
    if growth:
        insights.append({"tipo": "crecimiento", "icon": "🚀",
            "titulo": f"{_cap(growth['store'])} incrementó {growth['pct']:.0f}% sus ofertas esta semana."})

    return {"items": insights}


def _store_growth() -> dict[str, Any] | None:
    """Tienda con mayor crecimiento de ofertas (7 días vs 7 días previos)."""
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    sql = text("""
        WITH cur AS (
            SELECT sp.store, COUNT(*) AS n FROM price_history ph
            JOIN store_products sp ON sp.id = ph.store_product_id
            WHERE ph.scraped_at >= NOW() - INTERVAL '7 days'
            GROUP BY sp.store
        ),
        prev AS (
            SELECT sp.store, COUNT(*) AS n FROM price_history ph
            JOIN store_products sp ON sp.id = ph.store_product_id
            WHERE ph.scraped_at >= NOW() - INTERVAL '14 days'
              AND ph.scraped_at <  NOW() - INTERVAL '7 days'
            GROUP BY sp.store
        )
        SELECT cur.store, cur.n, COALESCE(prev.n, 0) AS prev_n
        FROM cur LEFT JOIN prev ON prev.store = cur.store
        WHERE COALESCE(prev.n, 0) >= 20
    """)
    best = None
    try:
        with Session(_engine) as s:
            for row in s.execute(sql).all():
                store, cur_n, prev_n = row[0], int(row[1]), int(row[2])
                if prev_n <= 0:
                    continue
                pct = (cur_n - prev_n) / prev_n * 100
                # Rango realista (evita artefactos por repoblados masivos)
                if 5 < pct <= 200 and (best is None or pct > best["pct"]):
                    best = {"store": store, "pct": round(pct, 1)}
    except Exception:
        return None
    return best
