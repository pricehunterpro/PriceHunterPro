"""Portafolio — registro y control de productos comprados para reventa.

Persistencia en Redis (`portfolio:items`), consistente con Publicador y TikTok.
Los campos derivados (total_cost, estimated_profit, roi, real_profit) se calculan
en el backend a partir de los campos editables.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException

router = APIRouter(prefix="/bi/portfolio", tags=["bi-portfolio"])

_KEY = "portfolio:items"
ESTADOS = ["Comprado", "En tránsito", "Recibido", "Publicado", "Vendido", "Cancelado"]


def _r():
    import redis as _redis
    from app.core.config import get_settings
    return _redis.from_url(get_settings().redis_url)


def _all() -> list[dict]:
    raw = _r().get(_KEY) or b"[]"
    return json.loads(raw)


def _save(items: list[dict]) -> None:
    _r().set(_KEY, json.dumps(items, default=str))


def _find(items: list[dict], item_id: str) -> dict:
    for it in items:
        if it["id"] == item_id:
            return it
    raise HTTPException(status_code=404, detail="Producto no encontrado en el portafolio")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _compute(it: dict) -> dict:
    """Recalcula los campos derivados a partir de los editables."""
    qty      = max(1, int(_f(it.get("quantity"), 1)))
    compra   = _f(it.get("purchase_price"))
    sugerido = _f(it.get("suggested_sale_price"))
    final    = _f(it.get("final_sale_price"))

    it["quantity"]      = qty
    it["total_cost"]    = round(compra * qty, 2)
    it["estimated_profit"] = round((sugerido - compra) * qty, 2)
    it["roi"] = round((sugerido - compra) / compra * 100, 1) if compra > 0 else 0.0
    it["real_profit"] = round((final - compra) * qty, 2) if final > 0 else 0.0
    return it


# ── Listado ──────────────────────────────────────────────────────────────────
@router.get("")
def list_items(status: str | None = None) -> dict[str, Any]:
    items = _all()
    if status:
        items = [i for i in items if i.get("status") == status]
    items.sort(key=lambda i: i.get("created_at", ""), reverse=True)
    return {"items": items, "estados": ESTADOS, "total": len(items)}


# ── Resumen / KPIs ───────────────────────────────────────────────────────────
@router.get("/summary")
def summary() -> dict[str, Any]:
    items = _all()
    activos = [i for i in items if i.get("status") != "Cancelado"]
    vendidos = [i for i in items if i.get("status") == "Vendido"]
    en_portafolio = [i for i in items if i.get("status") not in ("Vendido", "Cancelado")]

    inversion   = round(sum(_f(i.get("total_cost")) for i in activos), 2)
    gan_est     = round(sum(_f(i.get("estimated_profit")) for i in activos), 2)
    gan_real    = round(sum(_f(i.get("real_profit")) for i in vendidos), 2)
    roi_prom    = round(sum(_f(i.get("roi")) for i in activos) / len(activos), 1) if activos else 0.0

    por_estado = {e: sum(1 for i in items if i.get("status") == e) for e in ESTADOS}

    return {
        "kpis": {
            "inversionTotal":       inversion,
            "gananciaEstimada":     gan_est,
            "gananciaReal":         gan_real,
            "productosEnPortafolio": len(en_portafolio),
            "productosVendidos":    len(vendidos),
            "roiPromedio":          roi_prom,
        },
        "porEstado": por_estado,
    }


# ── Crear ────────────────────────────────────────────────────────────────────
@router.post("")
def create(body: dict = Body(...)) -> dict[str, Any]:
    if not (body.get("product_name") or "").strip():
        raise HTTPException(status_code=400, detail="El nombre del producto es obligatorio")
    status = body.get("status") or "Comprado"
    if status not in ESTADOS:
        raise HTTPException(status_code=400, detail="Estado inválido")

    now = _now()
    it = {
        "id":                   str(uuid.uuid4()),
        "opportunity_id":       body.get("opportunity_id") or None,
        "product_name":         str(body["product_name"])[:160],
        "store":                body.get("store") or "",
        "category":             body.get("category") or "General",
        "quantity":             int(_f(body.get("quantity"), 1)) or 1,
        "purchase_price":       _f(body.get("purchase_price")),
        "suggested_sale_price": _f(body.get("suggested_sale_price")),
        "final_sale_price":     _f(body.get("final_sale_price")),
        "status":               status,
        "purchase_date":        body.get("purchase_date") or now,
        "sale_date":            body.get("sale_date") or None,
        "notes":                body.get("notes") or "",
        "image_url":            body.get("image_url") or "",
        "created_at":           now,
        "updated_at":           now,
    }
    _compute(it)
    items = _all()
    items.append(it)
    _save(items)
    return {"status": "ok", "item": it}


# ── Editar ───────────────────────────────────────────────────────────────────
@router.put("/{item_id}")
def update(item_id: str, body: dict = Body(...)) -> dict[str, Any]:
    items = _all()
    it = _find(items, item_id)

    editable = [
        "product_name", "store", "category", "quantity", "purchase_price",
        "suggested_sale_price", "final_sale_price", "status", "purchase_date",
        "sale_date", "notes", "image_url",
    ]
    for f in editable:
        if f in body:
            it[f] = body[f]

    if "status" in body and body["status"] not in ESTADOS:
        raise HTTPException(status_code=400, detail="Estado inválido")

    # Al marcar como Vendido, fija la fecha de venta si no se envió
    if it.get("status") == "Vendido" and not it.get("sale_date"):
        it["sale_date"] = _now()

    it["updated_at"] = _now()
    _compute(it)
    _save(items)
    return {"status": "ok", "item": it}


# ── Eliminar ─────────────────────────────────────────────────────────────────
@router.delete("/{item_id}")
def delete(item_id: str) -> dict[str, str]:
    items = _all()
    _find(items, item_id)  # 404 si no existe
    items = [i for i in items if i["id"] != item_id]
    _save(items)
    return {"status": "ok"}
