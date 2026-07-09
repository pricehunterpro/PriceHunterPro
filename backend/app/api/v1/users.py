"""Usuarios — administración de usuarios del sistema (RBAC + multi-tenant).

Registro persistente en Redis (`users:registry`). Contraseñas hasheadas con
passlib (mismo esquema que el resto del sistema). Preparado para múltiples
empresas (tenant_id). El login (`auth.admin_login`) valida también contra este
registro, así los usuarios creados aquí pueden autenticarse.
"""
from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from app.core.security import get_password_hash

router = APIRouter(prefix="/users", tags=["users"])

_KEY = "users:registry"

ROLES = ["Administrador", "Supervisor", "Editor", "Analista", "Invitado"]
MODULOS = ["Dashboard", "Oportunidades", "Inteligencia IA", "Marketing",
           "Business Intelligence", "Automatización", "Administración"]

# RBAC: módulos accesibles por rol
ROLE_PERMISOS: dict[str, list[str]] = {
    "Administrador": MODULOS,
    "Supervisor":    ["Dashboard", "Oportunidades", "Inteligencia IA", "Marketing", "Business Intelligence", "Automatización"],
    "Editor":        ["Dashboard", "Oportunidades", "Marketing"],
    "Analista":      ["Dashboard", "Oportunidades", "Inteligencia IA", "Business Intelligence"],
    "Invitado":      ["Dashboard", "Oportunidades"],
}
# Rol interno para el JWT (isAdmin ve todo el menú)
_JWT_ROLE = {"Administrador": "superadmin", "Supervisor": "superadmin"}

TENANTS = ["PriceHunter Pro"]


def _r():
    import redis as _redis
    from app.core.config import get_settings
    return _redis.from_url(get_settings().redis_url)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _all() -> list[dict]:
    raw = _r().get(_KEY)
    if not raw:
        return _seed()
    return json.loads(raw)


def _save(items: list[dict]) -> None:
    _r().set(_KEY, json.dumps(items, default=str))


def _public(u: dict) -> dict:
    """Sin el hash de contraseña."""
    return {k: v for k, v in u.items() if k != "password_hash"}


def _seed() -> list[dict]:
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    presets = [
        ("PriceHunter Admin", "pricehunterpro@gmail.com", "Administrador", "Activo", 0),
        ("Usuario Prueba 1",  "user_prueba1@pricehunter.pe", "Invitado", "Activo", 3),
        ("Usuario Prueba 2",  "user_prueba2@pricehunter.pe", "Analista", "Activo", 26),
    ]
    items = []
    for nombre, email, role, status, hrs in presets:
        items.append({
            "id": str(uuid.uuid4()),
            "nombre": nombre, "email": email, "role": role, "status": status,
            "tenant_id": "PriceHunter Pro",
            "password_hash": get_password_hash("changeme"),
            "permisos": ROLE_PERMISOS.get(role, []),
            "last_access": (now - timedelta(hours=hrs)).isoformat(),
            "created_at": (now - timedelta(days=30)).isoformat(),
            "updated_at": now.isoformat(),
        })
    _r().set(_KEY, json.dumps(items, default=str))
    return items


def _find(items: list[dict], uid: str) -> dict:
    for it in items:
        if it["id"] == uid:
            return it
    raise HTTPException(status_code=404, detail="Usuario no encontrado")


# ── Metadatos ────────────────────────────────────────────────────────────────
@router.get("/roles")
def roles() -> dict[str, Any]:
    return {"roles": ROLES, "permisos": ROLE_PERMISOS, "modulos": MODULOS, "tenants": TENANTS}


@router.get("/stats")
def stats() -> dict[str, Any]:
    from datetime import timedelta
    items = _all()
    day_ago = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    return {
        "kpis": {
            "activos":        sum(1 for u in items if u["status"] == "Activo"),
            "inactivos":      sum(1 for u in items if u["status"] != "Activo"),
            "administradores": sum(1 for u in items if u["role"] == "Administrador"),
            "ultimosIngresos": sum(1 for u in items if (u.get("last_access") or "") >= day_ago),
            "total":          len(items),
        },
    }


# ── Listado ──────────────────────────────────────────────────────────────────
@router.get("")
def list_users(role: str | None = None, status: str | None = None, q: str | None = None) -> dict[str, Any]:
    items = _all()
    if role:   items = [u for u in items if u["role"] == role]
    if status: items = [u for u in items if u["status"] == status]
    if q:
        ql = q.lower()
        items = [u for u in items if ql in u["nombre"].lower() or ql in u["email"].lower()]
    items = sorted(items, key=lambda u: u.get("created_at") or "", reverse=True)
    return {"items": [_public(u) for u in items], "total": len(items),
            "roles": ROLES, "tenants": TENANTS}


@router.get("/{uid}")
def get_one(uid: str) -> dict[str, Any]:
    return {"item": _public(_find(_all(), uid))}


# ── Crear ────────────────────────────────────────────────────────────────────
@router.post("")
def create(body: dict = Body(...)) -> dict[str, Any]:
    nombre = (body.get("nombre") or "").strip()
    email = (body.get("email") or "").strip().lower()
    if not nombre or not email:
        raise HTTPException(status_code=400, detail="Nombre y correo son obligatorios")
    role = body.get("role") if body.get("role") in ROLES else "Invitado"
    items = _all()
    if any(u["email"].lower() == email for u in items):
        raise HTTPException(status_code=400, detail="Ya existe un usuario con ese correo")

    password = body.get("password") or secrets.token_urlsafe(8)
    now = _now()
    u = {
        "id": str(uuid.uuid4()),
        "nombre": nombre[:120], "email": email, "role": role,
        "status": body.get("status") if body.get("status") in ("Activo", "Inactivo") else "Activo",
        "tenant_id": body.get("tenant_id") or "PriceHunter Pro",
        "password_hash": get_password_hash(password),
        "permisos": ROLE_PERMISOS.get(role, []),
        "last_access": None, "created_at": now, "updated_at": now,
    }
    items.append(u)
    _save(items)
    return {"status": "ok", "item": _public(u), "password_temporal": password if not body.get("password") else None}


# ── Editar ───────────────────────────────────────────────────────────────────
@router.put("/{uid}")
def update(uid: str, body: dict = Body(...)) -> dict[str, Any]:
    items = _all()
    u = _find(items, uid)
    if "nombre" in body: u["nombre"] = str(body["nombre"])[:120]
    if "email" in body:
        email = str(body["email"]).strip().lower()
        if any(x["email"].lower() == email and x["id"] != uid for x in items):
            raise HTTPException(status_code=400, detail="Correo ya usado por otro usuario")
        u["email"] = email
    if body.get("role") in ROLES:
        u["role"] = body["role"]
        u["permisos"] = ROLE_PERMISOS.get(body["role"], [])
    if body.get("status") in ("Activo", "Inactivo"):
        u["status"] = body["status"]
    if body.get("tenant_id"):
        u["tenant_id"] = body["tenant_id"]
    u["updated_at"] = _now()
    _save(items)
    return {"status": "ok", "item": _public(u)}


# ── Cambiar estado ───────────────────────────────────────────────────────────
@router.post("/{uid}/toggle-status")
def toggle_status(uid: str) -> dict[str, Any]:
    items = _all()
    u = _find(items, uid)
    u["status"] = "Inactivo" if u["status"] == "Activo" else "Activo"
    u["updated_at"] = _now()
    _save(items)
    return {"status": "ok", "item": _public(u)}


# ── Restablecer contraseña ───────────────────────────────────────────────────
@router.post("/{uid}/reset-password")
def reset_password(uid: str, body: dict = Body(default={})) -> dict[str, Any]:
    items = _all()
    u = _find(items, uid)
    nueva = body.get("password") or secrets.token_urlsafe(8)
    u["password_hash"] = get_password_hash(nueva)
    u["updated_at"] = _now()
    _save(items)
    return {"status": "ok", "password_temporal": nueva}


# ── Cambiar rol ──────────────────────────────────────────────────────────────
@router.post("/{uid}/role")
def change_role(uid: str, body: dict = Body(...)) -> dict[str, Any]:
    role = body.get("role")
    if role not in ROLES:
        raise HTTPException(status_code=400, detail="Rol inválido")
    items = _all()
    u = _find(items, uid)
    u["role"] = role
    u["permisos"] = ROLE_PERMISOS.get(role, [])
    u["updated_at"] = _now()
    _save(items)
    return {"status": "ok", "item": _public(u)}


@router.delete("/{uid}")
def delete(uid: str) -> dict[str, str]:
    items = _all()
    _find(items, uid)
    _save([u for u in items if u["id"] != uid])
    return {"status": "ok"}


# ── Usado por el login (auth.admin_login) ────────────────────────────────────
def authenticate(username: str, password: str) -> dict | None:
    """Valida credenciales contra el registro. Devuelve datos para el JWT o None."""
    from app.core.security import verify_password
    uname = (username or "").strip().lower()
    items = _all()
    for u in items:
        if u["status"] != "Activo":
            continue
        if u["email"].lower() == uname or u["nombre"].lower() == uname:
            if verify_password(password, u.get("password_hash", "")):
                u["last_access"] = _now()
                _save(items)
                return {"subject": u["email"], "role": _JWT_ROLE.get(u["role"], "viewer"), "user": _public(u)}
    return None
