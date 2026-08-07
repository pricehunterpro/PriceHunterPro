"""Acceso a la configuración de la plataforma (tabla `system_configurations`).

Es la ÚNICA puerta a la configuración. Cualquier módulo que quiera dejar de tener
un valor hardcodeado hace:

    from app.services.settings_service import get_setting
    timeout = get_setting("scrapers", "timeout")        # 30

`get_setting` nunca revienta ni bloquea: si la tabla todavía no existe, si Supabase
no responde o si la clave no está sembrada, devuelve el default del catálogo. Por
eso se puede adoptar módulo por módulo sin coordinar despliegues.

Escala por ambiente (regla 4): cada fila lleva `environment`, y se lee el del
`.env` activo. Desarrollo, QA y Producción conviven en la misma base.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services import settings_catalog as cat
from app.services.deal_service import _engine  # mismo pool ya afinado para Supabase

_CACHE_TTL = 30
_cache: dict[str, Any] = {"ts": 0.0, "env": None, "data": None}
_cache_filas: dict[str, Any] = {"ts": 0.0, "env": None, "data": None}


def ambiente_actual() -> str:
    return (get_settings().environment or "development").strip().lower()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Lectura ──────────────────────────────────────────────────────────────────
def _leer_crudo(env: str, sesion: Session | None = None) -> dict[tuple[str, str], str]:
    """Valores guardados para el ambiente. {} si la tabla aún no existe.

    Acepta una Session ya abierta para no gastar otra conexión del pooler.
    """
    sql = text("SELECT category, key, value FROM system_configurations WHERE environment = :env")
    try:
        if sesion is not None:
            rows = sesion.execute(sql, {"env": env}).fetchall()
        else:
            with Session(_engine) as s:
                rows = s.execute(sql, {"env": env}).fetchall()
        return {(r.category, r.key): r.value for r in rows}
    except Exception:
        # Tabla inexistente o BD caída: se opera con los defaults del catálogo.
        return {}


def _valores(force: bool = False) -> dict[tuple[str, str], Any]:
    """Estado completo (default del catálogo pisado por lo guardado)."""
    env = ambiente_actual()
    ahora = time.time()
    if (
        not force
        and _cache["data"] is not None
        and _cache["env"] == env
        and (ahora - _cache["ts"]) < _CACHE_TTL
    ):
        return _cache["data"]

    guardado = _leer_crudo(env)
    out: dict[tuple[str, str], Any] = {}
    for d in cat.CATALOGO:
        clave = (d.category, d.key)
        if clave in guardado:
            out[clave] = cat.from_text(guardado[clave], d.type)
        else:
            out[clave] = d.default
    _cache.update(ts=ahora, env=env, data=out)
    return out


def invalidar_cache() -> None:
    _cache.update(ts=0.0, data=None)
    _cache_filas.update(ts=0.0, data=None)


def get_setting(category: str, key: str, default: Any = None) -> Any:
    """Valor efectivo de un ajuste. Nunca lanza excepción."""
    try:
        valor = _valores().get((category, key))
        if valor is not None:
            return valor
    except Exception:
        pass
    d = cat.definicion(category, key)
    if d is not None:
        return d.default
    return default


def get_category(category: str) -> dict[str, Any]:
    """Todos los ajustes de una categoría como {clave: valor}."""
    return {k: v for (c, k), v in _valores().items() if c == category}


def snapshot() -> dict[str, dict[str, Any]]:
    """Configuración completa agrupada por categoría."""
    out: dict[str, dict[str, Any]] = {}
    for (c, k), v in _valores().items():
        out.setdefault(c, {})[k] = v
    return out


def _filas(env: str) -> dict[tuple[str, str], dict[str, Any]]:
    """Valor + metadatos en UNA sola consulta.

    El pooler de Supabase está en modo sesión con tope de 15 clientes, así que
    cada Session extra cuenta: la pantalla de Configuración pide las 10
    categorías de una vez y antes abría dos conexiones por categoría.
    Cacheado junto con los valores.
    """
    ahora = time.time()
    if (
        _cache_filas["data"] is not None
        and _cache_filas["env"] == env
        and (ahora - _cache_filas["ts"]) < _CACHE_TTL
    ):
        return _cache_filas["data"]
    try:
        with Session(_engine) as s:
            rows = s.execute(
                text("""
                    SELECT category, key, value, updated_by, updated_at
                    FROM system_configurations
                    WHERE environment = :env
                """),
                {"env": env},
            ).fetchall()
        data = {
            (r.category, r.key): {
                "value": r.value,
                "updated_by": r.updated_by,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        }
    except Exception:
        data = {}
    _cache_filas.update(ts=ahora, env=env, data=data)
    return data


def detalle_categoria(category: str) -> list[dict[str, Any]]:
    """Ajustes de una categoría con su definición, valor y metadatos de edición."""
    filas = _filas(ambiente_actual())
    salida = []
    for d in cat.por_categoria(category):
        fila = filas.get((d.category, d.key))
        item = d.public()
        item["value"] = cat.from_text(fila["value"], d.type) if fila else d.default
        item["is_default"] = fila is None
        item["updated_by"] = fila["updated_by"] if fila else None
        item["updated_at"] = fila["updated_at"] if fila else None
        salida.append(item)
    return salida


# ── Escritura ────────────────────────────────────────────────────────────────
def guardar(cambios: list[dict[str, Any]], updated_by: str) -> dict[str, Any]:
    """Valida y persiste una tanda de cambios. Todo o nada.

    `cambios` = [{"category": ..., "key": ..., "value": ...}, ...]
    Devuelve el resumen de lo aplicado (solo lo que realmente cambió de valor).
    """
    if not cambios:
        return {"aplicados": 0, "cambios": []}

    env = ambiente_actual()

    # 1. Cada valor contra su definición.
    normalizados: list[tuple[cat.SettingDef, Any]] = []
    for c in cambios:
        d = cat.definicion(str(c.get("category", "")), str(c.get("key", "")))
        if d is None:
            raise cat.ValidationError(
                f"Ajuste desconocido: {c.get('category')}.{c.get('key')}"
            )
        normalizados.append((d, cat.validar_valor(d, c.get("value"))))

    # 2. El conjunto RESULTANTE (lo actual + los cambios), no solo el cambio: las
    #    reglas cruzadas (pesos que suman, umbrales ordenados) necesitan el estado
    #    final completo o rechazarían cambios válidos.
    estado = dict(_valores(force=True))
    for d, v in normalizados:
        estado[(d.category, d.key)] = v
    cat.validar_conjunto(estado)

    # 3. Persistir + auditar en una sola transacción (y una sola conexión).
    aplicados: list[dict[str, Any]] = []
    auditar = bool(get_setting("seguridad", "auditoria", True))

    with Session(_engine) as s:
        previos = _leer_crudo(env, s)
        for d, valor in normalizados:
            nuevo_txt = cat.to_text(valor)
            anterior_txt = previos.get((d.category, d.key))
            if anterior_txt is None:
                anterior_txt = cat.to_text(d.default)
            if anterior_txt == nuevo_txt:
                continue  # sin cambio real: no ensucia la bitácora

            s.execute(
                text("""
                    INSERT INTO system_configurations
                        (id, environment, category, key, value, value_type, description, updated_by, created_at, updated_at)
                    VALUES
                        (:id, :env, :cat, :key, :val, :vtype, :desc, :by, :now, :now)
                    ON CONFLICT (environment, category, key) DO UPDATE
                        SET value = EXCLUDED.value,
                            value_type = EXCLUDED.value_type,
                            description = EXCLUDED.description,
                            updated_by = EXCLUDED.updated_by,
                            updated_at = EXCLUDED.updated_at
                """),
                {
                    "id": str(uuid.uuid4()), "env": env, "cat": d.category, "key": d.key,
                    "val": nuevo_txt, "vtype": d.type, "desc": d.description,
                    "by": updated_by, "now": _now(),
                },
            )

            if auditar:
                s.execute(
                    text("""
                        INSERT INTO system_configuration_audit
                            (id, environment, category, key, old_value, new_value, updated_by, created_at)
                        VALUES (:id, :env, :cat, :key, :old, :new, :by, :now)
                    """),
                    {
                        "id": str(uuid.uuid4()), "env": env, "cat": d.category, "key": d.key,
                        "old": anterior_txt, "new": nuevo_txt, "by": updated_by, "now": _now(),
                    },
                )

            aplicados.append({
                "category": d.category, "key": d.key, "label": d.label,
                "old_value": cat.from_text(anterior_txt, d.type), "new_value": valor,
            })
        s.commit()

    invalidar_cache()
    return {"aplicados": len(aplicados), "cambios": aplicados}


def resetear(category: str | None, updated_by: str) -> dict[str, Any]:
    """Vuelve una categoría (o todo) a los defaults del catálogo.

    Borra las filas personalizadas; el valor efectivo pasa a ser el default.
    """
    env = ambiente_actual()
    auditar = bool(get_setting("seguridad", "auditoria", True))
    with Session(_engine) as s:
        previos = _leer_crudo(env, s)
        objetivo = [
            d for d in cat.CATALOGO
            if (category is None or d.category == category) and (d.category, d.key) in previos
        ]
        if category:
            s.execute(
                text("DELETE FROM system_configurations WHERE environment = :env AND category = :cat"),
                {"env": env, "cat": category},
            )
        else:
            s.execute(
                text("DELETE FROM system_configurations WHERE environment = :env"),
                {"env": env},
            )
        if auditar:
            for d in objetivo:
                s.execute(
                    text("""
                        INSERT INTO system_configuration_audit
                            (id, environment, category, key, old_value, new_value, updated_by, created_at)
                        VALUES (:id, :env, :cat, :key, :old, :new, :by, :now)
                    """),
                    {
                        "id": str(uuid.uuid4()), "env": env, "cat": d.category, "key": d.key,
                        "old": previos.get((d.category, d.key)),
                        "new": cat.to_text(d.default),
                        "by": f"{updated_by} (reset)", "now": _now(),
                    },
                )
        s.commit()

    invalidar_cache()
    return {"restaurados": len(objetivo), "categoria": category or "todas"}


def historial(limite: int = 50, category: str | None = None) -> list[dict[str, Any]]:
    """Últimos cambios registrados (regla 3: usuario, fecha, antes y después)."""
    env = ambiente_actual()
    sql = """
        SELECT category, key, old_value, new_value, updated_by, created_at
        FROM system_configuration_audit
        WHERE environment = :env
    """
    params: dict[str, Any] = {"env": env, "lim": limite}
    if category:
        sql += " AND category = :cat"
        params["cat"] = category
    sql += " ORDER BY created_at DESC LIMIT :lim"

    try:
        with Session(_engine) as s:
            rows = s.execute(text(sql), params).fetchall()
        return [
            {
                "category": r.category,
                "key": r.key,
                "label": (cat.definicion(r.category, r.key).label if cat.definicion(r.category, r.key) else r.key),
                "old_value": r.old_value,
                "new_value": r.new_value,
                "updated_by": r.updated_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    except Exception:
        return []


def personalizados() -> int:
    """Cuántos ajustes están fuera del default (KPI 'configuraciones activas')."""
    return len(_leer_crudo(ambiente_actual()))
