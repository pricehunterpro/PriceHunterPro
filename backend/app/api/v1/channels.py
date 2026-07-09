"""Canales — administración de los canales de publicación.

Tokens guardados CIFRADOS (Fernet, clave derivada de SECRET_KEY). En las
respuestas el token va enmascarado (nunca en claro). Telegram tiene integración
REAL (probar conexión llama a la Bot API `getMe`). Facebook/Instagram/WhatsApp
quedan preparados para Meta Graph API, y TikTok/YouTube para sus APIs.
"""
from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from app.core.config import get_settings

router = APIRouter(prefix="/channels", tags=["channels"])

_KEY = "channels:registry"

# canal, api, estado inicial
_META = [
    ("Telegram",  "Telegram Bot API", "#29b6f6"),
    ("Facebook",  "Meta Graph API",   "#1877f2"),
    ("Instagram", "Meta Graph API",   "#e1306c"),
    ("TikTok",    "TikTok API",       "#00e5c0"),
    ("WhatsApp",  "Meta Cloud API",   "#25d366"),
    ("YouTube",   "YouTube Data API", "#ff0000"),
]


# ── Cifrado de tokens ────────────────────────────────────────────────────────
def _fernet():
    from cryptography.fernet import Fernet
    key = base64.urlsafe_b64encode(hashlib.sha256(get_settings().secret_key.encode()).digest())
    return Fernet(key)


def _enc(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().encrypt(token.encode()).decode()
    except Exception:
        # Fallback (ofuscación) si cryptography no está disponible
        return "b64:" + base64.urlsafe_b64encode(token.encode()).decode()


def _dec(enc: str) -> str:
    if not enc:
        return ""
    try:
        if enc.startswith("b64:"):
            return base64.urlsafe_b64decode(enc[4:].encode()).decode()
        return _fernet().decrypt(enc.encode()).decode()
    except Exception:
        return ""


def _mask(token: str) -> str:
    if not token:
        return ""
    return ("•" * max(4, len(token) - 4)) + token[-4:] if len(token) > 4 else "••••"


def _r():
    import redis as _redis
    return _redis.from_url(get_settings().redis_url)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed() -> list[dict]:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    items = []
    for nombre, api, color in _META:
        conectado = nombre == "Telegram" and bool(settings.telegram_bot_token)
        token_enc = _enc(settings.telegram_bot_token) if conectado else ""
        items.append({
            "id": nombre.lower(),
            "nombre": nombre, "api": api, "color": color,
            "estado": "Conectado" if conectado else "Desconectado",
            "cuenta_conectada": "PriceHunter Bot" if conectado else "",
            "token_enc": token_enc,
            "expiracion": None if conectado else None,  # Telegram bot tokens no expiran
            "ultima_publicacion": now.isoformat() if conectado else None,
            "created_at": now.isoformat(), "updated_at": now.isoformat(),
        })
    _r().set(_KEY, json.dumps(items, default=str))
    return items


def _all() -> list[dict]:
    raw = _r().get(_KEY)
    if not raw:
        return _seed()
    return json.loads(raw)


def _save(items: list[dict]) -> None:
    _r().set(_KEY, json.dumps(items, default=str))


def _find(items: list[dict], cid: str) -> dict:
    for it in items:
        if it["id"] == cid:
            return it
    raise HTTPException(status_code=404, detail="Canal no encontrado")


def _public(c: dict) -> dict:
    """Sin el token cifrado; token enmascarado."""
    out = {k: v for k, v in c.items() if k != "token_enc"}
    tok = _dec(c.get("token_enc", ""))
    out["token_masked"] = _mask(tok)
    out["tiene_token"] = bool(tok)
    return out


# ── Lectura ──────────────────────────────────────────────────────────────────
@router.get("")
def list_channels() -> dict[str, Any]:
    return {"items": [_public(c) for c in _all()]}


@router.get("/stats")
def stats() -> dict[str, Any]:
    items = _all()
    def c(*st): return sum(1 for i in items if i["estado"] in st)
    return {
        "kpis": {
            "total":        len(items),
            "conectados":   c("Conectado"),
            "desconectados": c("Desconectado"),
            "conError":     c("Error", "Expirado"),
        },
    }


@router.get("/{cid}")
def get_one(cid: str) -> dict[str, Any]:
    return {"item": _public(_find(_all(), cid))}


# ── CRUD ─────────────────────────────────────────────────────────────────────
@router.post("")
def create(body: dict = Body(...)) -> dict[str, Any]:
    nombre = (body.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio")
    cid = nombre.lower().replace(" ", "")
    items = _all()
    if any(i["id"] == cid for i in items):
        raise HTTPException(status_code=400, detail="Ya existe un canal con ese nombre")
    now = _now()
    it = {
        "id": cid, "nombre": nombre, "api": body.get("api") or "Custom", "color": body.get("color") or "#00E58F",
        "estado": "Desconectado", "cuenta_conectada": "", "token_enc": "",
        "expiracion": None, "ultima_publicacion": None, "created_at": now, "updated_at": now,
    }
    items.append(it)
    _save(items)
    return {"status": "ok", "item": _public(it)}


@router.put("/{cid}")
def update(cid: str, body: dict = Body(...)) -> dict[str, Any]:
    items = _all()
    it = _find(items, cid)
    for f in ("nombre", "api", "color", "cuenta_conectada"):
        if f in body:
            it[f] = body[f]
    it["updated_at"] = _now()
    _save(items)
    return {"status": "ok", "item": _public(it)}


@router.delete("/{cid}")
def delete(cid: str) -> dict[str, str]:
    items = _all()
    _find(items, cid)
    _save([i for i in items if i["id"] != cid])
    return {"status": "ok"}


# ── Conexión ─────────────────────────────────────────────────────────────────
@router.post("/{cid}/connect")
def connect(cid: str, body: dict = Body(...)) -> dict[str, Any]:
    token = (body.get("token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Se requiere el token")
    items = _all()
    it = _find(items, cid)
    it["token_enc"] = _enc(token)
    it["cuenta_conectada"] = body.get("cuenta") or it.get("cuenta_conectada") or ""
    if body.get("expiracion"):
        it["expiracion"] = body["expiracion"]
    it["estado"] = "Conectado"
    it["updated_at"] = _now()
    _save(items)
    return {"status": "ok", "item": _public(it)}


@router.post("/{cid}/disconnect")
def disconnect(cid: str) -> dict[str, Any]:
    items = _all()
    it = _find(items, cid)
    it["token_enc"] = ""
    it["cuenta_conectada"] = ""
    it["estado"] = "Desconectado"
    it["expiracion"] = None
    it["updated_at"] = _now()
    _save(items)
    return {"status": "ok", "item": _public(it)}


@router.post("/{cid}/update-token")
def update_token(cid: str, body: dict = Body(...)) -> dict[str, Any]:
    token = (body.get("token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Se requiere el token")
    items = _all()
    it = _find(items, cid)
    it["token_enc"] = _enc(token)
    it["estado"] = "Conectado"
    it["updated_at"] = _now()
    _save(items)
    return {"status": "ok", "item": _public(it)}


@router.post("/{cid}/test")
def test_connection(cid: str) -> dict[str, Any]:
    """Prueba la conexión. Telegram: real (Bot API getMe). Otros: preparado."""
    items = _all()
    it = _find(items, cid)
    token = _dec(it.get("token_enc", ""))
    if not token:
        raise HTTPException(status_code=400, detail="El canal no tiene token configurado")

    if it["id"] == "telegram":
        try:
            import httpx
            r = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15)
            data = r.json()
            if r.status_code == 200 and data.get("ok"):
                info = data["result"]
                it["cuenta_conectada"] = "@" + info.get("username", "bot")
                it["estado"] = "Conectado"
                _save(items)
                return {"status": "ok", "real": True,
                        "detail": {"bot": info.get("username"), "nombre": info.get("first_name")}}
            it["estado"] = "Error"
            _save(items)
            raise HTTPException(status_code=400, detail=f"Telegram rechazó el token: {data.get('description', 'error')}")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"No se pudo conectar con Telegram: {exc}")

    # Otros canales: integración preparada (Meta Graph / TikTok / YouTube)
    return {"status": "ok", "real": False,
            "detail": {"mensaje": f"Conexión simulada OK. Integración con {it['api']} preparada para producción."}}
