"""Plantillas — administración de plantillas visuales para generar contenido.

Toda la configuración visual se guarda como JSON dinámico (`config_json`), sin
plantillas fijas en código. Persistencia en Redis (`templates:items`), como el
resto de estado mutable del proyecto (Publicador, TikTok, Portafolio).

Reutilizable por Publicador IA y TikTok Factory (mismo `config_json`).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException

router = APIRouter(prefix="/templates", tags=["templates"])

_KEY = "templates:items"

CANALES = ["Telegram", "Facebook", "Instagram", "TikTok", "YouTube Shorts", "WhatsApp"]
CATEGORIAS = [
    "Flash Sale", "Mega Oferta", "Precio Histórico", "Top Oferta", "Gaming",
    "Tecnología", "Electrohogar", "Moda", "Hogar", "Ferretería", "Supermercado",
]
ESTADOS = ["Activa", "Borrador"]

# Resolución sugerida por canal
_RESOLUCION = {
    "Telegram": "1080x1080", "Facebook": "1200x630", "Instagram": "1080x1350",
    "TikTok": "1080x1920", "YouTube Shorts": "1080x1920", "WhatsApp": "1080x1080",
}

_POSICIONES = [
    "top-left", "top-center", "top-right",
    "center-left", "center", "center-right",
    "bottom-left", "bottom-center", "bottom-right",
]


def _r():
    import redis as _redis
    from app.core.config import get_settings
    return _redis.from_url(get_settings().redis_url)


def _all() -> list[dict]:
    raw = _r().get(_KEY) or b"[]"
    return json.loads(raw)


def _save(items: list[dict]) -> None:
    _r().set(_KEY, json.dumps(items, default=str))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_config(color: str = "#00E58F") -> dict:
    return {
        "logo": "",
        "colorPrincipal": color,
        "colorSecundario": "#0d1117",
        "tipografia": "Inter",
        "posiciones": {
            "producto": "center", "precio": "bottom-left", "descuento": "top-right",
            "scoreIA": "top-left", "botonComprar": "bottom-center", "qr": "bottom-right",
            "tienda": "top-center", "marca": "bottom-left",
        },
        "elementos": {
            "logo": True, "precioAnterior": True, "precioActual": True, "descuento": True,
            "scoreIA": True, "marca": True, "categoria": False, "tienda": True,
            "qr": False, "cta": True, "hashtags": True, "fecha": False,
        },
    }


def _seed() -> list[dict]:
    presets = [
        ("Flash Sale Telegram", "Telegram", "Flash Sale", "#00E58F", "Activa", 42),
        ("Mega Oferta TikTok",  "TikTok",   "Mega Oferta", "#ff3b6b", "Activa", 87),
        ("Gaming Instagram",    "Instagram","Gaming",      "#7c3aed", "Activa", 31),
        ("Tech Facebook",       "Facebook", "Tecnología",  "#2563eb", "Activa", 19),
        ("Precio Histórico WA", "WhatsApp", "Precio Histórico", "#25D366", "Borrador", 5),
        ("Top Oferta Shorts",   "YouTube Shorts", "Top Oferta", "#ff0000", "Borrador", 8),
    ]
    items = []
    for nombre, canal, cat, color, estado, usos in presets:
        now = _now()
        items.append({
            "id": str(uuid.uuid4()),
            "nombre": nombre, "canal": canal, "categoria": cat,
            "tipo": "post", "resolucion": _RESOLUCION.get(canal, "1080x1080"),
            "config_json": _default_config(color),
            "estado": estado, "usos": usos,
            "created_at": now, "updated_at": now,
        })
    _save(items)
    return items


def _find(items: list[dict], tid: str) -> dict:
    for it in items:
        if it["id"] == tid:
            return it
    raise HTTPException(status_code=404, detail="Plantilla no encontrada")


# ── Metadatos (declarar antes de /{id}) ──────────────────────────────────────
@router.get("/channels")
def channels() -> dict[str, Any]:
    return {"channels": CANALES, "resoluciones": _RESOLUCION, "posiciones": _POSICIONES}


@router.get("/categories")
def categories() -> dict[str, Any]:
    return {"categories": CATEGORIAS, "estados": ESTADOS}


@router.get("/summary")
def summary() -> dict[str, Any]:
    items = _all()
    if not items:
        items = _seed()
    activas = [i for i in items if i.get("estado") == "Activa"]
    borradores = [i for i in items if i.get("estado") == "Borrador"]
    mas_usada = max(items, key=lambda i: i.get("usos", 0)) if items else None
    ultima = max((i.get("updated_at", "") for i in items), default="")
    return {
        "kpis": {
            "totalPlantillas":     len(items),
            "plantillasActivas":   len(activas),
            "plantillasBorrador":  len(borradores),
            "plantillaMasUsada":   mas_usada["nombre"] if mas_usada else "—",
            "plantillaMasUsadaUsos": mas_usada.get("usos", 0) if mas_usada else 0,
            "ultimaModificacion":  ultima,
        },
    }


# ── Listado ──────────────────────────────────────────────────────────────────
@router.get("")
def list_templates(canal: str | None = None, categoria: str | None = None, estado: str | None = None) -> dict[str, Any]:
    items = _all()
    if not items:
        items = _seed()
    if canal:
        items = [i for i in items if i.get("canal") == canal]
    if categoria:
        items = [i for i in items if i.get("categoria") == categoria]
    if estado:
        items = [i for i in items if i.get("estado") == estado]
    items.sort(key=lambda i: i.get("updated_at", ""), reverse=True)
    return {"items": items, "channels": CANALES, "categories": CATEGORIAS, "estados": ESTADOS, "total": len(items)}


# ── Crear ────────────────────────────────────────────────────────────────────
@router.post("")
def create(body: dict = Body(...)) -> dict[str, Any]:
    nombre = (body.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio")
    canal = body.get("canal") or "Telegram"
    if canal not in CANALES:
        raise HTTPException(status_code=400, detail="Canal inválido")

    now = _now()
    it = {
        "id": str(uuid.uuid4()),
        "nombre": nombre[:120],
        "canal": canal,
        "categoria": body.get("categoria") or "Flash Sale",
        "tipo": body.get("tipo") or "post",
        "resolucion": body.get("resolucion") or _RESOLUCION.get(canal, "1080x1080"),
        "config_json": body.get("config_json") or _default_config(),
        "estado": body.get("estado") if body.get("estado") in ESTADOS else "Borrador",
        "usos": 0,
        "created_at": now, "updated_at": now,
    }
    items = _all()
    items.append(it)
    _save(items)
    return {"status": "ok", "item": it}


# ── Duplicar ─────────────────────────────────────────────────────────────────
@router.post("/{tid}/duplicate")
def duplicate(tid: str) -> dict[str, Any]:
    items = _all()
    src = _find(items, tid)
    now = _now()
    copy = {
        **json.loads(json.dumps(src, default=str)),
        "id": str(uuid.uuid4()),
        "nombre": f"{src['nombre']} (copia)",
        "estado": "Borrador", "usos": 0,
        "created_at": now, "updated_at": now,
    }
    items.append(copy)
    _save(items)
    return {"status": "ok", "item": copy}


# ── Detalle / Editar / Eliminar ──────────────────────────────────────────────
@router.get("/{tid}")
def get_one(tid: str) -> dict[str, Any]:
    return {"item": _find(_all(), tid)}


@router.put("/{tid}")
def update(tid: str, body: dict = Body(...)) -> dict[str, Any]:
    items = _all()
    it = _find(items, tid)
    for f in ("nombre", "canal", "categoria", "tipo", "resolucion", "config_json", "estado"):
        if f in body:
            it[f] = body[f]
    if it.get("estado") not in ESTADOS:
        it["estado"] = "Borrador"
    it["updated_at"] = _now()
    _save(items)
    return {"status": "ok", "item": it}


@router.delete("/{tid}")
def delete(tid: str) -> dict[str, str]:
    items = _all()
    _find(items, tid)
    _save([i for i in items if i["id"] != tid])
    return {"status": "ok"}
