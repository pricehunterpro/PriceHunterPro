"""Rentabilidad — potencial de reventa de las oportunidades detectadas.

Reutiliza el dataset puntuado del Motor IA (`_scored` → `calculate_score`).
No modifica el Motor IA.

Modelo de reventa (realista):
- precio_compra          = precio actual (precio de oferta)
- margen_reventa         = escala con la profundidad del descuento (a mayor
                           descuento, mayor recorrido de reventa), con tope 75%.
                           Un revendedor no puede vender al precio lista de la
                           tienda, así que NO se usa el precio lista como venta.
- precio_sugerido_venta  = precio_compra * (1 + margen_reventa), y nunca por
                           encima del precio histórico/lista de referencia.
- ganancia               = precio_sugerido_venta - precio_compra
- ROI                    = ganancia / precio_compra * 100
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.v1.ai_trends import _parse_list, _scored

router = APIRouter(prefix="/bi/profitability", tags=["bi-profitability"])

_RENTABLE_ROI = 25  # umbral para considerar un producto "rentable"


def _clasificar(roi: float) -> str:
    if roi > 50:
        return "Alta rentabilidad"
    if roi >= 25:
        return "Buena rentabilidad"
    if roi >= 10:
        return "Rentabilidad media"
    return "Baja rentabilidad"


def _recomendacion(roi: float, score: int) -> str:
    if roi > 50 and score >= 70:
        return "Comprar y revender ya"
    if roi >= 25:
        return "Comprar para revender"
    if roi >= 10:
        return "Evaluar"
    return "Descartar"


def _profit_row(d: dict[str, Any]) -> dict[str, Any] | None:
    compra = float(d.get("currentPrice", 0) or 0)
    if compra <= 0:
        return None
    disc = float(d.get("discountPct", 0) or 0)
    avg  = float(d.get("avgMarketPrice", 0) or 0)
    orig = float(d.get("originalPrice", 0) or 0)

    # Margen de reventa realista: crece con el descuento, tope 75%.
    resale = min(0.75, (disc / 100.0) * 0.72)
    sugerido = round(compra * (1 + resale), 2)

    # Nunca sugerir por encima de la referencia real de mercado (histórico/lista)
    techo = max(avg, orig)
    if techo > compra and sugerido > techo:
        sugerido = round(techo, 2)
    if sugerido < compra:
        sugerido = compra

    ganancia = round(sugerido - compra, 2)
    roi = round(ganancia / compra * 100, 1) if compra > 0 else 0.0

    return {
        "id":             d.get("id"),
        "name":           d.get("name"),
        "store":          d.get("store"),
        "category":       d.get("category"),
        "imageUrl":       d.get("imageUrl", ""),
        "url":            d.get("url", ""),
        "precioCompra":   round(compra, 2),
        "precioSugerido": sugerido,
        "ganancia":       ganancia,
        "roi":            roi,
        "margen":         round(float(d.get("marginPct", 0) or 0), 1),
        "score":          d.get("score", 0),
        "clasificacion":  _clasificar(roi),
        "recomendacion":  _recomendacion(roi, int(d.get("score", 0) or 0)),
    }


def _rows(store, category, brand, min_score) -> list[dict[str, Any]]:
    items = _scored(_parse_list(store), _parse_list(category), brand, min_score)
    rows = [r for r in (_profit_row(d) for d in items) if r]
    return rows


@router.get("/summary")
def summary(
    store=Query(None), category=Query(None), brand=Query(None), min_score: int = Query(0),
) -> dict[str, Any]:
    rows = _rows(store, category, brand, min_score)
    rentables = [r for r in rows if r["roi"] >= _RENTABLE_ROI]

    ganancia_total = round(sum(r["ganancia"] for r in rentables), 2)
    capital        = round(sum(r["precioCompra"] for r in rentables), 2)
    roi_prom       = round(sum(r["roi"] for r in rentables) / len(rentables), 1) if rentables else 0.0
    mayor_margen   = round(max((r["roi"] for r in rows), default=0), 1)

    return {
        "kpis": {
            "gananciaPotencialTotal": ganancia_total,
            "roiPromedio":            roi_prom,
            "productosRentables":     len(rentables),
            "capitalRequerido":       capital,
            "mayorMargenDetectado":   mayor_margen,
        },
        "clasificaciones": {
            "alta":  sum(1 for r in rows if r["clasificacion"] == "Alta rentabilidad"),
            "buena": sum(1 for r in rows if r["clasificacion"] == "Buena rentabilidad"),
            "media": sum(1 for r in rows if r["clasificacion"] == "Rentabilidad media"),
            "baja":  sum(1 for r in rows if r["clasificacion"] == "Baja rentabilidad"),
        },
    }


@router.get("/products")
def products(
    store=Query(None), category=Query(None), brand=Query(None), min_score: int = Query(0),
    clasificacion: str | None = Query(default=None),
    sort: str = Query(default="roi", description="roi|ganancia|score|margen"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    rows = _rows(store, category, brand, min_score)
    if clasificacion:
        rows = [r for r in rows if r["clasificacion"] == clasificacion]

    keymap = {"ganancia": "ganancia", "score": "score", "margen": "margen"}
    key = keymap.get(sort, "roi")
    rows.sort(key=lambda r: r[key], reverse=True)

    total = len(rows)
    start = (page - 1) * limit
    return {"items": rows[start: start + limit], "total": total}
