"""Centro de Configuración — Administración → Configuración.

Sirve el catálogo, guarda cambios (validados y auditados) y expone el estado de
sistema, base de datos e integraciones.

Reutiliza en lugar de duplicar:
  - Canales (`/api/v1/channels`) para las 6 integraciones de publicación, que ya
    guarda los tokens cifrados. Acá solo se LEEN y se suman OpenAI y SMTP.
  - Scrapers (`/api/v1/scrapers`) para el KPI de scrapers activos.
  - `deal_service._engine` para consultar el estado de la base.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services import settings_catalog as cat
from app.services import settings_service as svc
from app.services.deal_service import _engine

router = APIRouter(prefix="/settings", tags=["settings"])

_APP_START = time.time()


def _actor(body: dict[str, Any] | None = None) -> str:
    """Quién hace el cambio. El front manda `updated_by`; si no, el admin del .env.

    La app no tiene aún un usuario en el request (no hay dependencia de auth en
    estos routers), así que se toma del cuerpo y se cae al admin configurado.
    """
    if body:
        quien = str(body.get("updated_by") or "").strip()
        if quien:
            return quien[:120]
    return get_settings().admin_user or "admin"


# ── Estado de sistema ────────────────────────────────────────────────────────
def _leer_int(path: str) -> int | None:
    try:
        with open(path) as f:
            return int(f.read().strip())
    except Exception:
        return None


def _memoria() -> dict[str, Any]:
    """Memoria del contenedor (cgroup v2) o del host como respaldo."""
    usado = _leer_int("/sys/fs/cgroup/memory.current")
    limite = _leer_int("/sys/fs/cgroup/memory.max")
    if usado is not None and limite is not None and limite > 0:
        return {
            "usadoMb": round(usado / 1048576, 1),
            "totalMb": round(limite / 1048576, 1),
            "porcentaje": round(usado / limite * 100, 1),
            "fuente": "cgroup",
        }
    try:
        info: dict[str, int] = {}
        with open("/proc/meminfo") as f:
            for linea in f:
                partes = linea.split()
                if len(partes) >= 2:
                    info[partes[0].rstrip(":")] = int(partes[1])  # kB
        total = info.get("MemTotal", 0)
        disponible = info.get("MemAvailable", 0)
        usado_kb = total - disponible
        return {
            "usadoMb": round(usado_kb / 1024, 1),
            "totalMb": round(total / 1024, 1),
            "porcentaje": round(usado_kb / total * 100, 1) if total else 0.0,
            "fuente": "meminfo",
        }
    except Exception:
        return {"usadoMb": 0.0, "totalMb": 0.0, "porcentaje": 0.0, "fuente": "n/d"}


def _cpu() -> dict[str, Any]:
    """Carga por load average — no bloquea el request como sí lo haría muestrear."""
    try:
        uno, cinco, quince = os.getloadavg()
        nucleos = os.cpu_count() or 1
        return {
            "porcentaje": round(min(100.0, uno / nucleos * 100), 1),
            "load1": round(uno, 2),
            "load5": round(cinco, 2),
            "load15": round(quince, 2),
            "nucleos": nucleos,
        }
    except Exception:
        return {"porcentaje": 0.0, "load1": 0.0, "load5": 0.0, "load15": 0.0, "nucleos": os.cpu_count() or 1}


def _disco() -> dict[str, Any]:
    try:
        st = os.statvfs("/")
        total = st.f_blocks * st.f_frsize
        libre = st.f_bavail * st.f_frsize
        usado = total - libre
        return {
            "usadoGb": round(usado / 1073741824, 2),
            "totalGb": round(total / 1073741824, 2),
            "porcentaje": round(usado / total * 100, 1) if total else 0.0,
        }
    except Exception:
        return {"usadoGb": 0.0, "totalGb": 0.0, "porcentaje": 0.0}


def _uptime() -> dict[str, Any]:
    proceso = time.time() - _APP_START
    contenedor = None
    try:
        with open("/proc/uptime") as f:
            contenedor = float(f.read().split()[0])
    except Exception:
        pass
    segundos = contenedor or proceso

    def _humano(s: float) -> str:
        s = int(s)
        d, resto = divmod(s, 86400)
        h, resto = divmod(resto, 3600)
        m, _ = divmod(resto, 60)
        if d:
            return f"{d}d {h}h {m}m"
        if h:
            return f"{h}h {m}m"
        return f"{m}m"

    return {
        "segundos": int(segundos),
        "texto": _humano(segundos),
        "procesoSegundos": int(proceso),
        "procesoTexto": _humano(proceso),
    }


def _estado_bd() -> dict[str, Any]:
    cfg = get_settings()
    url = cfg.database_url
    motor = "PostgreSQL (Supabase)" if "supabase" in url else "PostgreSQL"
    salida: dict[str, Any] = {
        "conectado": False,
        "motor": motor,
        "host": "",
        "tamano": "n/d",
        "tablas": 0,
        "filas": {},
        "ultimaMigracion": "",
        "ultimoBackup": None,
        "error": "",
    }
    try:
        from urllib.parse import urlsplit
        salida["host"] = urlsplit(url.replace("postgresql+asyncpg://", "postgresql://")).hostname or ""
    except Exception:
        pass

    try:
        with Session(_engine) as s:
            salida["conectado"] = True
            salida["version"] = str(s.execute(text("SELECT version()")).scalar() or "")[:60]
            salida["tamano"] = str(
                s.execute(text("SELECT pg_size_pretty(pg_database_size(current_database()))")).scalar() or "n/d"
            )
            salida["tablas"] = int(
                s.execute(text("""
                    SELECT count(*) FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                """)).scalar() or 0
            )
            try:
                salida["ultimaMigracion"] = str(
                    s.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar() or ""
                )
            except Exception:
                salida["ultimaMigracion"] = "sin registrar"
            # ESTIMADO vía pg_class.reltuples, no count(*): `price_history` tiene
            # millones de filas y un count exacto tardaba más que todo el resto
            # de la pantalla junta.
            filas: dict[str, int] = {}
            try:
                rows = s.execute(text("""
                    SELECT relname, GREATEST(reltuples, 0)::bigint AS estimado
                    FROM pg_class
                    WHERE relname IN ('products','store_products','price_history','users','system_configurations')
                      AND relkind = 'r'
                """)).fetchall()
                filas = {r.relname: int(r.estimado) for r in rows}
            except Exception:
                filas = {}
            salida["filas"] = filas
            salida["filasEstimadas"] = True
    except Exception as exc:
        salida["error"] = str(exc)[:200]

    salida["ultimoBackup"] = svc.get_setting("base_datos", "ultimo_backup", None)
    return salida


def _kpis() -> dict[str, Any]:
    """KPIs de la cabecera."""
    canales_total = canales_conectados = 0
    try:
        from app.api.v1.channels import _all as _canales
        items = _canales()
        canales_total = len(items)
        canales_conectados = sum(1 for c in items if c.get("estado") == "Conectado")
    except Exception:
        pass

    scrapers_activos = scrapers_total = 0
    try:
        from app.api.v1.scrapers import _all as _scrapers
        items = _scrapers()
        scrapers_total = len(items)
        scrapers_activos = sum(1 for s in items if s.get("status") == "Activo")
    except Exception:
        pass

    mem = _memoria()
    cpu = _cpu()
    # Chequeo de conectividad barato: `_estado_bd()` hace varias consultas y los
    # KPIs se piden en cada carga de la pantalla.
    try:
        with Session(_engine) as s:
            s.execute(text("SELECT 1"))
        bd_ok = True
    except Exception:
        bd_ok = False
    if not bd_ok:
        estado = "Crítico"
    elif mem["porcentaje"] > 90 or cpu["porcentaje"] > 90:
        estado = "Degradado"
    else:
        estado = "Operativo"

    # OpenAI y SMTP no viven en Canales: se cuentan aparte para el KPI.
    extras_conectados = sum([
        1 if svc.get_setting("integraciones", "openai_api_key") else 0,
        1 if svc.get_setting("integraciones", "smtp_host") else 0,
    ])

    return {
        "configuracionesActivas": svc.personalizados(),
        "configuracionesTotales": len(cat.CATALOGO),
        "integracionesConectadas": canales_conectados + extras_conectados,
        "integracionesTotales": canales_total + 2,
        "scrapersActivos": scrapers_activos,
        "scrapersTotales": scrapers_total,
        "canalesActivos": canales_conectados,
        "canalesTotales": canales_total,
        "estadoSistema": estado,
    }


# ── Endpoints ────────────────────────────────────────────────────────────────
# OJO: las rutas fijas van ANTES de /{category} o FastAPI las tomaría por
# categorías ("system-status" entraría como category).

@router.get("/system-status")
def system_status() -> dict[str, Any]:
    cfg = get_settings()
    return {
        "version": svc.get_setting("general", "version", "0.1.0"),
        # El ambiente sale del .env (es el que scopea la configuración leída), no
        # de un ajuste editable.
        "ambiente": svc.ambiente_actual(),
        "ambienteReal": cfg.environment,
        "memoria": _memoria(),
        "cpu": _cpu(),
        "disco": _disco(),
        "uptime": _uptime(),
        "python": sys.version.split()[0],
        "baseDatos": _estado_bd(),
        "kpis": _kpis(),
    }


@router.get("/integrations")
def integrations() -> dict[str, Any]:
    """Estado de las 8 integraciones.

    Las 6 de publicación se leen del módulo Canales (fuente de verdad, con los
    tokens cifrados); OpenAI y SMTP se arman con la configuración de esta pestaña.
    """
    items: list[dict[str, Any]] = []
    try:
        from app.api.v1.channels import _public, _all as _canales
        for c in _canales():
            pub = _public(c)
            items.append({
                "id": pub["id"],
                "nombre": pub["nombre"],
                "tipo": pub.get("api", ""),
                "color": pub.get("color", "#00E58F"),
                "estado": pub.get("estado", "Desconectado"),
                "ultimaSincronizacion": pub.get("ultima_publicacion"),
                "token": pub.get("token_masked", ""),
                "tieneToken": pub.get("tiene_token", False),
                "expiracion": pub.get("expiracion"),
                "cuenta": pub.get("cuenta_conectada", ""),
                # Estas acciones las atiende el módulo Canales, que ya las implementa.
                "gestionadoPor": "channels",
                "endpointBase": f"/api/v1/channels/{pub['id']}",
                "preparado": pub["id"] not in ("telegram",),
            })
    except Exception:
        pass

    openai_key = str(svc.get_setting("integraciones", "openai_api_key", "") or "")
    smtp_host = str(svc.get_setting("integraciones", "smtp_host", "") or "")
    items.append({
        "id": "openai", "nombre": "OpenAI", "tipo": "OpenAI API", "color": "#10a37f",
        "estado": "Conectado" if openai_key else "Desconectado",
        "ultimaSincronizacion": None,
        "token": ("•" * 8 + openai_key[-4:]) if len(openai_key) > 4 else "",
        "tieneToken": bool(openai_key), "expiracion": None,
        "cuenta": str(svc.get_setting("integraciones", "openai_modelo", "") or ""),
        "gestionadoPor": "settings", "endpointBase": "", "preparado": True,
    })
    items.append({
        "id": "smtp", "nombre": "SMTP", "tipo": "Correo saliente", "color": "#6ab0ff",
        "estado": "Conectado" if smtp_host else "Desconectado",
        "ultimaSincronizacion": None, "token": "", "tieneToken": False, "expiracion": None,
        "cuenta": f"{smtp_host}:{svc.get_setting('integraciones', 'smtp_puerto', 587)}" if smtp_host else "",
        "gestionadoPor": "settings", "endpointBase": "", "preparado": True,
    })

    conectadas = sum(1 for i in items if i["estado"] == "Conectado")
    return {
        "items": items,
        "kpis": {"total": len(items), "conectadas": conectadas, "desconectadas": len(items) - conectadas},
    }


@router.get("/audit")
def audit(
    limit: int = Query(default=50, ge=1, le=500),
    category: str | None = Query(default=None),
) -> dict[str, Any]:
    """Bitácora de cambios: usuario, fecha, valor anterior y valor nuevo."""
    return {"items": svc.historial(limit, category)}


@router.put("")
def update_settings(body: dict = Body(...)) -> dict[str, Any]:
    """Guarda una tanda de cambios. Valida todo antes de escribir: o entra todo o no entra nada."""
    cambios = body.get("changes") or body.get("cambios") or []
    if not isinstance(cambios, list):
        raise HTTPException(status_code=400, detail="`changes` debe ser una lista.")
    try:
        resultado = svc.guardar(cambios, _actor(body))
    except cat.ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", **resultado}


@router.post("/reset")
def reset_settings(body: dict = Body(default={})) -> dict[str, Any]:
    """Restaura los valores por defecto del catálogo (una categoría o todas)."""
    category = body.get("category") or body.get("categoria")
    if category and category not in cat.categorias_validas():
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    resultado = svc.resetear(category, _actor(body))
    return {"status": "ok", **resultado}


@router.post("/clear-cache")
def clear_cache() -> dict[str, Any]:
    """Limpia las cachés en memoria (configuración, ofertas, tendencias, recomendaciones)."""
    limpiadas: list[str] = []
    svc.invalidar_cache()
    limpiadas.append("configuración")

    try:
        from app.services.deal_service import _items_cache
        _items_cache.update(ts=0.0, items=None)
        limpiadas.append("catálogo de ofertas")
    except Exception:
        pass
    try:
        from app.api.v1.ai_trends import _cache as _trends_cache
        _trends_cache.update(key=None, ts=0.0, data=None)
        limpiadas.append("tendencias")
    except Exception:
        pass
    try:
        from app.api.v1.ai_recommendations import _cache as _recs_cache
        _recs_cache.update(ts=0.0, data=None)
        limpiadas.append("recomendaciones")
    except Exception:
        pass

    return {"status": "ok", "limpiadas": limpiadas}


@router.get("")
def get_all_settings() -> dict[str, Any]:
    """Catálogo completo con los valores efectivos del ambiente activo."""
    return {
        "ambiente": svc.ambiente_actual(),
        "categorias": cat.CATEGORIAS,
        "secciones": {c["id"]: svc.detalle_categoria(c["id"]) for c in cat.CATEGORIAS},
        "kpis": _kpis(),
    }


@router.get("/{category}")
def get_category_settings(category: str) -> dict[str, Any]:
    if category not in cat.categorias_validas():
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    meta = next(c for c in cat.CATEGORIAS if c["id"] == category)
    return {
        "categoria": meta,
        "ambiente": svc.ambiente_actual(),
        "items": svc.detalle_categoria(category),
    }
