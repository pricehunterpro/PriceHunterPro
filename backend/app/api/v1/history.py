"""Historial de Precios — Centro de Inteligencia Histórica.

Lee la tabla REAL `price_history` (append-only: cada cambio de precio es un
registro nuevo — reglas 1 y 2 ya garantizadas por el pipeline de scraping).
Reutiliza el PriceHunter Score (Motor IA). Sirve de base para Motor IA,
Recomendaciones IA, Ranking IA y Analytics (regla 3).

Identificador de "producto" = store_product_id (producto en una tienda concreta,
con su propia serie histórica).
"""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from app.ai.scorer import calculate_score
from app.services.deal_service import _engine

router = APIRouter(prefix="/history", tags=["history"])

_PERIODS = {"7d": "7 days", "30d": "30 days", "90d": "90 days", "180d": "180 days", "1y": "365 days"}


def _score(current, discount, original, avg, in_stock, store, category) -> int:
    margin = ((original - current) / current * 100) if current > 0 and original and original > current else 0
    deal = {
        "currentPrice": current, "discountPct": discount or 0, "marginPct": margin,
        "avgMarketPrice": avg or 0, "belowMarket": bool(avg and current < avg * 0.85),
        "mktDiffPct": ((1 - current / avg) * 100) if avg else 0,
        "inStock": in_stock, "store": store, "category": category,
    }
    return calculate_score(deal)["score"]


def _session():
    from sqlalchemy.orm import Session
    return Session(_engine)


# ── Listado paginado ─────────────────────────────────────────────────────────
# Umbral de "sin cambio": ±0.5%. Es el MISMO que usa `varClass()` en el front
# para pintar la columna, así que filtrar "bajó de precio" devuelve exactamente
# las filas que se ven en verde.
_VAR_EPS = 0.5


@router.get("")
def list_history(
    q: str | None = None, store: str | None = None, category: str | None = None,
    brand: str | None = None, min_price: float = 0, max_price: float = 0,
    min_score: int = 0,
    var_dir: str | None = Query(None, description="down = bajó de precio | up = subió | eq = sin cambio"),
    min_var: float = Query(0, ge=0, le=100, description="Magnitud mínima de la variación, en %"),
    sort: str = Query("recent", description="recent | var_asc (mayor caída primero) | var_desc"),
    page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    from sqlalchemy import text

    where = ["sp.current_price > 0"]
    params: dict[str, Any] = {}
    if q:
        where.append("(p.name ILIKE :q OR COALESCE(p.brand,'') ILIKE :q OR COALESCE(p.category,'') ILIKE :q OR sp.store ILIKE :q)")
        params["q"] = f"%{q}%"
    if store:    where.append("sp.store = :store");     params["store"] = store
    if category: where.append("p.category = :cat");     params["cat"] = category
    if brand:    where.append("p.brand = :brand");      params["brand"] = brand
    if min_price: where.append("sp.current_price >= :minp"); params["minp"] = min_price
    if max_price: where.append("sp.current_price <= :maxp"); params["maxp"] = max_price
    wsql = " AND ".join(where)

    # La variación se compara contra el promedio histórico, que sale del GROUP BY,
    # así que el filtro va en HAVING (no en WHERE). Hacerlo en SQL y no en Python
    # importa: si no, la página se llenaría de filas descartadas y "bajó ≥50%"
    # devolvería casi nada aunque existan coincidencias.
    var_dir = (var_dir or "").lower() or None
    having = ""
    if var_dir in ("down", "up", "eq"):
        pct = "(c.cp - AVG(ph.price)) / NULLIF(AVG(ph.price), 0) * 100"
        umbral = max(min_var, _VAR_EPS) if var_dir != "eq" else _VAR_EPS
        params["var_umbral"] = umbral
        if var_dir == "down":
            having = f"HAVING {pct} <= -:var_umbral"
        elif var_dir == "up":
            having = f"HAVING {pct} >= :var_umbral"
        else:
            having = f"HAVING ABS({pct}) < :var_umbral"

    # Con filtro de variación se amplía el pool de candidatos: los 800 más
    # recientes rara vez alcanzan para llenar una página de "bajó ≥50%".
    params["cand_limit"] = 2500 if var_dir else 800

    sql = text(f"""
        WITH cand AS (
            SELECT sp.id, sp.product_id, sp.store, CAST(sp.current_price AS float) cp,
                   CAST(sp.original_price AS float) op, CAST(sp.discount_percentage AS float) disc,
                   sp.in_stock, sp.store_sku, sp.url, sp.last_scraped_at
            FROM store_products sp JOIN products p ON p.id = sp.product_id
            WHERE {wsql}
            ORDER BY sp.last_scraped_at DESC NULLS LAST
            LIMIT :cand_limit
        )
        SELECT c.id, p.name, COALESCE(p.brand,'') brand, COALESCE(p.category,'General') category,
               c.store, c.cp, c.op, c.disc, c.in_stock, c.store_sku, c.url, COALESCE(p.image_url,'') img,
               CAST(MIN(ph.price) AS float) pmin, CAST(MAX(ph.price) AS float) pmax,
               CAST(AVG(ph.price) AS float) pavg, COUNT(ph.id) n, MAX(ph.scraped_at) last
        FROM cand c JOIN products p ON p.id = c.product_id
        JOIN price_history ph ON ph.store_product_id = c.id AND ph.price > 0
        GROUP BY c.id, p.name, p.brand, p.category, c.store, c.cp, c.op, c.disc,
                 c.in_stock, c.store_sku, c.url, p.image_url
        {having}
    """)

    rows = []
    with _session() as s:
        for r in s.execute(sql, params).all():
            current = r.cp or 0
            pavg = r.pavg or 0
            score = _score(current, r.disc, r.op, pavg, r.in_stock, r.store, r.category)
            if min_score and score < min_score:
                continue
            variacion = round((current - pavg) / pavg * 100, 1) if pavg else 0.0
            rows.append({
                "id": r.id, "name": r.name, "brand": r.brand, "category": r.category, "store": r.store,
                "sku": r.store_sku or "", "url": r.url or "", "imageUrl": r.img, "inStock": bool(r.in_stock),
                "currentPrice": round(current, 2), "precioMin": round(r.pmin or 0, 2),
                "precioMax": round(r.pmax or 0, 2), "precioProm": round(pavg, 2),
                "cambios": int(r.n or 0), "ultimoCambio": r.last.isoformat() if r.last else None,
                "variacionPct": variacion, "score": score,
                "esMinimo": abs(current - (r.pmin or 0)) < 0.01,
                "ahorroVsProm": round(pavg - current, 2) if pavg > current else 0.0,
            })

    if sort == "var_asc":        # mayor caída primero: lo que más conviene comprar
        rows.sort(key=lambda x: x["variacionPct"])
    elif sort == "var_desc":
        rows.sort(key=lambda x: x["variacionPct"], reverse=True)
    else:
        rows.sort(key=lambda x: x["ultimoCambio"] or "", reverse=True)

    total = len(rows)
    start = (page - 1) * limit
    return {
        "items": rows[start:start + limit], "total": total, "page": page, "limit": limit,
        "resumen": {
            "bajaron":   sum(1 for x in rows if x["variacionPct"] <= -_VAR_EPS),
            "subieron":  sum(1 for x in rows if x["variacionPct"] >= _VAR_EPS),
            "sinCambio": sum(1 for x in rows if abs(x["variacionPct"]) < _VAR_EPS),
        },
    }


# ── KPIs globales ────────────────────────────────────────────────────────────
@router.get("/stats")
def stats() -> dict[str, Any]:
    from sqlalchemy import text
    with _session() as s:
        base = s.execute(text("""
            SELECT COUNT(DISTINCT store_product_id) prods, COUNT(*) cambios,
                   CAST(MIN(price) AS float) pmin, CAST(MAX(price) AS float) pmax,
                   MAX(scraped_at) last
            FROM price_history WHERE price > 0
        """)).first()
        var = s.execute(text("""
            SELECT CAST(AVG(rng) AS float) FROM (
                SELECT (MAX(price) - MIN(price)) / NULLIF(MIN(price),0) * 100 rng
                FROM price_history WHERE price > 0
                GROUP BY store_product_id HAVING COUNT(*) > 1
                LIMIT 5000
            ) t
        """)).scalar()
    return {
        "kpis": {
            "productosConHistorial": int(base.prods or 0),
            "cambiosRegistrados":    int(base.cambios or 0),
            "precioMinHistorico":    round(base.pmin or 0, 2),
            "precioMaxHistorico":    round(base.pmax or 0, 2),
            "variacionPromedio":     round(var or 0, 1),
            "ultimaSincronizacion":  base.last.isoformat() if base.last else None,
        },
    }


# ── Detalle general ──────────────────────────────────────────────────────────
@router.get("/{pid}")
def get_detail(pid: str) -> dict[str, Any]:
    from sqlalchemy import text
    with _session() as s:
        r = s.execute(text("""
            SELECT sp.id, p.name, COALESCE(p.brand,'') brand, COALESCE(p.category,'General') category,
                   sp.store, sp.store_sku, sp.url, sp.in_stock, COALESCE(p.image_url,'') img,
                   CAST(sp.current_price AS float) cp, CAST(sp.original_price AS float) op,
                   CAST(sp.discount_percentage AS float) disc,
                   CAST(MIN(ph.price) AS float) pmin, CAST(MAX(ph.price) AS float) pmax,
                   CAST(AVG(ph.price) AS float) pavg, COUNT(ph.id) n,
                   MIN(ph.scraped_at) first, MAX(ph.scraped_at) last
            FROM store_products sp JOIN products p ON p.id = sp.product_id
            JOIN price_history ph ON ph.store_product_id = sp.id AND ph.price > 0
            WHERE sp.id = :id
            GROUP BY sp.id, p.name, p.brand, p.category, sp.store, sp.store_sku, sp.url,
                     sp.in_stock, p.image_url, sp.current_price, sp.original_price, sp.discount_percentage
        """), {"id": pid}).first()
    if not r:
        raise HTTPException(status_code=404, detail="Producto sin historial")

    current = r.cp or 0
    pmin = r.pmin or 0
    dias = (r.last - r.first).days + 1 if r.first and r.last else 1
    mayor_desc = round((r.pmax - pmin) / r.pmax * 100, 1) if r.pmax else 0
    score = _score(current, r.disc, r.op, r.pavg or 0, r.in_stock, r.store, r.category)

    # Alertas
    subio = current > (r.pavg or 0)
    alertas = {
        "esMinimoHistorico": abs(current - pmin) < 0.01,
        "subioDePrecio": current > pmin * 1.001,
        "bajoDePrecio": current < (r.pmax or 0) * 0.999,
        "volvioAlMinimo": abs(current - pmin) < 0.01 and (r.pmax or 0) > pmin * 1.01,
    }
    return {
        "item": {
            "id": r.id, "name": r.name, "brand": r.brand, "category": r.category, "store": r.store,
            "sku": r.store_sku or "", "url": r.url or "", "imageUrl": r.img, "inStock": bool(r.in_stock),
            "score": score,
            "stats": {
                "precioMin": round(pmin, 2), "precioMax": round(r.pmax or 0, 2),
                "precioProm": round(r.pavg or 0, 2), "precioActual": round(current, 2),
                "variacion": round((current - (r.pavg or 0)) / (r.pavg or 1) * 100, 1) if r.pavg else 0,
                "mayorDescuento": mayor_desc, "diasMonitoreados": dias, "cambios": int(r.n or 0),
            },
            "alertas": alertas,
        },
    }


# ── Gráfico histórico ────────────────────────────────────────────────────────
@router.get("/chart/{pid}")
def chart(pid: str, period: str = Query("90d")) -> dict[str, Any]:
    from sqlalchemy import text
    interval = _PERIODS.get(period, "90 days")
    with _session() as s:
        avg_all = s.execute(text("SELECT CAST(AVG(price) AS float) FROM price_history WHERE store_product_id=:id AND price>0"),
                            {"id": pid}).scalar() or 0
        ctx = s.execute(text("SELECT sp.store, COALESCE(p.category,'') cat, CAST(sp.original_price AS float) op, sp.in_stock FROM store_products sp JOIN products p ON p.id=sp.product_id WHERE sp.id=:id"),
                        {"id": pid}).first()
        rows = s.execute(text(f"""
            SELECT to_char(date_trunc('day', scraped_at), 'DD/MM') label,
                   date_trunc('day', scraped_at) d,
                   CAST(AVG(price) AS float) price,
                   CAST(AVG(CASE WHEN original_price>0 AND original_price>=price
                             THEN (original_price-price)/original_price*100 ELSE 0 END) AS float) disc
            FROM price_history
            WHERE store_product_id=:id AND price>0 AND scraped_at >= NOW() - INTERVAL '{interval}'
            GROUP BY 1,2 ORDER BY 2
        """), {"id": pid}).all()

    labels, precios, descuentos, scores = [], [], [], []
    store = ctx.store if ctx else ""
    cat = ctx.cat if ctx else ""
    op = ctx.op if ctx else 0
    stock = ctx.in_stock if ctx else True
    for r in rows:
        labels.append(r.label)
        precios.append(round(r.price, 2))
        descuentos.append(round(r.disc, 1))
        scores.append(_score(r.price, r.disc, op, avg_all, stock, store, cat))
    return {"period": period, "labels": labels, "precios": precios, "descuentos": descuentos, "scores": scores}


# ── Timeline de cambios ──────────────────────────────────────────────────────
@router.get("/timeline/{pid}")
def timeline(pid: str) -> dict[str, Any]:
    from sqlalchemy import text
    with _session() as s:
        rows = s.execute(text("""
            SELECT CAST(price AS float) price, scraped_at
            FROM price_history WHERE store_product_id=:id AND price>0
            ORDER BY scraped_at ASC
        """), {"id": pid}).all()

    out = []
    last_price = None
    pmin = min((r.price for r in rows), default=0)
    for r in rows:
        if last_price is None or abs(r.price - last_price) >= 0.01:
            direction = "="
            if last_price is not None:
                direction = "down" if r.price < last_price else "up"
            out.append({
                "fecha": r.scraped_at.isoformat() if r.scraped_at else None,
                "precio": round(r.price, 2),
                "direccion": direction,
                "esMinimo": abs(r.price - pmin) < 0.01,
            })
            last_price = r.price
    out.reverse()  # más reciente primero
    return {"items": out, "total": len(out)}


# ── Export CSV ───────────────────────────────────────────────────────────────
@router.get("/export/csv")
def export_csv(q: str | None = None, store: str | None = None, category: str | None = None,
               brand: str | None = None, var_dir: str | None = None, min_var: float = 0,
               sort: str = "recent") -> Response:
    # El CSV respeta el filtro de variación: si en pantalla estás viendo solo las
    # bajadas, el archivo trae eso mismo y no el listado completo.
    data = list_history(q=q, store=store, category=category, brand=brand,
                        var_dir=var_dir, min_var=min_var, sort=sort, page=1, limit=200)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["producto", "marca", "categoria", "tienda", "precio_actual", "precio_min",
                "precio_max", "precio_prom", "variacion_%", "ahorro_vs_prom", "cambios",
                "score", "ultimo_cambio"])
    for i in data["items"]:
        w.writerow([i["name"], i["brand"], i["category"], i["store"], i["currentPrice"],
                    i["precioMin"], i["precioMax"], i["precioProm"], i["variacionPct"],
                    i["ahorroVsProm"], i["cambios"], i["score"], i["ultimoCambio"]])
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=pricehunter_historial.csv"})
