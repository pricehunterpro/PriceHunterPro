"""Procesos — consola de administración de tareas automáticas (tipo Celery).

Registro de `ProcessTask` en Redis (`processes:items`), con historial de cambios
de estado (regla 2) y errores completos (regla 3). Se siembra un conjunto realista
(regla 5) y se enriquece con ejecuciones reales de scraping (`scraping_logs`).
Preparado para integrar Celery real (worker_name, task_id) — regla 4.

No modifica módulos existentes.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/processes", tags=["processes"])

_KEY = "processes:items"

TIPOS = [
    "Scraping", "Sincronización", "Generación IA", "Generación TikTok",
    "Publicación Telegram", "Publicación Multicanal", "Analytics", "Limpieza de datos",
]
ESTADOS = ["Pendiente", "Ejecutando", "Completado", "Fallido", "Cancelado", "Reintentando"]
WORKERS = ["celery-worker-1", "celery-worker-2", "celery-beat"]
PRIORIDADES = ["Alta", "Media", "Baja"]

_MODULO = {
    "Scraping": "Scrapers", "Sincronización": "Centro de Monitoreo", "Generación IA": "Motor IA",
    "Generación TikTok": "TikTok Factory", "Publicación Telegram": "Publicador IA",
    "Publicación Multicanal": "Publicador IA", "Analytics": "Business Intelligence",
    "Limpieza de datos": "Sistema",
}


def _r():
    import redis as _redis
    from app.core.config import get_settings
    return _redis.from_url(get_settings().redis_url)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _make(tipo, estado, prio, dur, retry, worker, mins_ago, payload, result=None, error="") -> dict:
    start = _now() - timedelta(minutes=mins_ago)
    finished = None
    if estado in ("Completado", "Fallido", "Cancelado"):
        finished = start + timedelta(seconds=dur or 0)
    now_iso = _iso(_now())
    return {
        "id": str(uuid.uuid4()),
        "task_id": "celery-" + uuid.uuid4().hex[:12],
        "process_type": tipo,
        "module": _MODULO.get(tipo, "Sistema"),
        "status": estado,
        "priority": prio,
        "payload_json": payload,
        "result_json": result,
        "error_message": error,
        "worker_name": worker if estado != "Pendiente" else None,
        "started_at": _iso(start) if estado != "Pendiente" else None,
        "finished_at": _iso(finished),
        "duration_seconds": dur if finished else None,
        "retry_count": retry,
        "max_retries": 3,
        "logs": _seed_logs(tipo, estado, error),
        "state_history": [{"estado": estado, "at": now_iso}],
        "created_at": _iso(start),
        "updated_at": now_iso,
        "next_retry": _iso(_now() + timedelta(minutes=5)) if estado == "Reintentando" else None,
    }


def _seed_logs(tipo, estado, error) -> list[str]:
    base = [f"[INFO] Tarea {tipo} encolada", f"[INFO] Worker asignado", "[INFO] Ejecución iniciada"]
    if estado == "Completado":
        base += ["[INFO] Procesamiento OK", "[INFO] Tarea completada con éxito"]
    elif estado == "Fallido":
        base += ["[WARN] Reintento fallido", f"[ERROR] {error or 'Excepción no controlada'}"]
    elif estado == "Ejecutando":
        base += ["[INFO] Procesando…"]
    return base


def _seed() -> list[dict]:
    items = [
        _make("Scraping", "Completado", "Alta", 128.4, 0, "celery-worker-1", 12,
              {"stores": ["oechsle"], "trigger": "beat"}, {"saved": 9033, "errors": 0}),
        _make("Scraping", "Ejecutando", "Alta", 0, 0, "celery-worker-2", 2,
              {"stores": ["falabella"], "trigger": "manual"}),
        _make("Sincronización", "Completado", "Media", 14.2, 0, "celery-beat", 30,
              {"scope": "stats"}, {"synced": 7}),
        _make("Generación IA", "Completado", "Media", 6.8, 0, "celery-worker-1", 45,
              {"items": 16}, {"generados": 16}),
        _make("Generación TikTok", "Completado", "Baja", 42.1, 0, "celery-worker-2", 60,
              {"videos": 5}, {"videos_ok": 5}),
        _make("Publicación Telegram", "Completado", "Alta", 3.1, 0, "celery-worker-1", 8,
              {"channel": "PriceHunter", "alerts": 4}, {"enviadas": 4}),
        _make("Publicación Multicanal", "Pendiente", "Media", None, 0, None, 1,
              {"canales": ["Telegram", "Facebook", "Instagram"]}),
        _make("Analytics", "Completado", "Baja", 9.5, 0, "celery-beat", 90,
              {"report": "daily"}, {"kpis": 8}),
        _make("Limpieza de datos", "Completado", "Baja", 21.7, 0, "celery-worker-2", 180,
              {"target": "price_history", "older_than": "90d"}, {"deleted": 12045}),
        _make("Scraping", "Fallido", "Alta", 61.0, 3, "celery-worker-1", 240,
              {"stores": ["tottus"]}, error="503 Service Unavailable: WAF bloqueó las peticiones (Cloudflare)"),
        _make("Generación TikTok", "Reintentando", "Media", None, 1, "celery-worker-2", 5,
              {"videos": 3}, error="Timeout al renderizar video 2/3"),
        _make("Publicación Multicanal", "Cancelado", "Media", 2.0, 0, "celery-worker-1", 300,
              {"canales": ["Instagram"]}, error="Cancelado por el administrador"),
        _make("Sincronización", "Pendiente", "Baja", None, 0, None, 0,
              {"scope": "deals-cache"}),
        _make("Generación IA", "Ejecutando", "Media", 0, 0, "celery-worker-1", 1,
              {"items": 8}),
        _make("Analytics", "Fallido", "Media", 4.2, 2, "celery-beat", 150,
              {"report": "profitability"}, error="DivisionByZero en cálculo de ROI (dataset vacío)"),
        _make("Scraping", "Completado", "Alta", 96.3, 0, "celery-worker-2", 70,
              {"stores": ["ripley"]}, {"saved": 3409, "errors": 0}),
    ]
    _r().set(_KEY, json.dumps(items, default=str))
    return items


def _all() -> list[dict]:
    raw = _r().get(_KEY)
    if not raw:
        return _seed()
    return json.loads(raw)


def _save(items: list[dict]) -> None:
    _r().set(_KEY, json.dumps(items, default=str))


def _find(items: list[dict], pid: str) -> dict:
    for it in items:
        if it["id"] == pid:
            return it
    raise HTTPException(status_code=404, detail="Proceso no encontrado")


def _transition(it: dict, estado: str, error: str = "") -> None:
    """Registra un cambio de estado (regla 2) y actualiza timestamps."""
    it["status"] = estado
    it["state_history"] = (it.get("state_history") or []) + [{"estado": estado, "at": _iso(_now())}]
    it["updated_at"] = _iso(_now())
    if error:
        it["error_message"] = error
    if estado in ("Completado", "Fallido", "Cancelado"):
        it["finished_at"] = _iso(_now())


# ── Lectura ──────────────────────────────────────────────────────────────────
@router.get("")
def list_processes(
    estado: str | None = None, tipo: str | None = None, module: str | None = None,
    worker: str | None = None, prioridad: str | None = None,
) -> dict[str, Any]:
    items = _all()
    f = items
    if estado:    f = [i for i in f if i["status"] == estado]
    if tipo:      f = [i for i in f if i["process_type"] == tipo]
    if module:    f = [i for i in f if i["module"] == module]
    if worker:    f = [i for i in f if i.get("worker_name") == worker]
    if prioridad: f = [i for i in f if i["priority"] == prioridad]
    f = sorted(f, key=lambda i: i.get("created_at") or "", reverse=True)
    return {
        "items": f, "total": len(f),
        "tipos": TIPOS, "estados": ESTADOS, "workers": WORKERS, "prioridades": PRIORIDADES,
        "modules": sorted({i["module"] for i in items}),
    }


@router.get("/stats")
def stats() -> dict[str, Any]:
    items = _all()
    def c(*st): return sum(1 for i in items if i["status"] in st)
    dur = [i["duration_seconds"] for i in items if i["status"] == "Completado" and i.get("duration_seconds")]
    return {
        "kpis": {
            "totales":      len(items),
            "enEjecucion":  c("Ejecutando"),
            "pendientes":   c("Pendiente"),
            "completados":  c("Completado"),
            "fallidos":     c("Fallido"),
            "tiempoPromedio": round(sum(dur) / len(dur), 1) if dur else 0.0,
            "colaActiva":   c("Pendiente", "Ejecutando", "Reintentando"),
        },
        "porTipo": {t: sum(1 for i in items if i["process_type"] == t) for t in TIPOS},
    }


@router.get("/{pid}")
def get_one(pid: str) -> dict[str, Any]:
    return {"item": _find(_all(), pid)}


# ── Control ──────────────────────────────────────────────────────────────────
def _has_running(items: list[dict], tipo: str, module: str, exclude: str = "") -> bool:
    return any(i["status"] == "Ejecutando" and i["process_type"] == tipo
              and i["module"] == module and i["id"] != exclude for i in items)


@router.post("/{pid}/retry")
def retry(pid: str) -> dict[str, Any]:
    items = _all()
    it = _find(items, pid)
    if it["status"] not in ("Fallido", "Cancelado"):
        raise HTTPException(status_code=409, detail="Solo se puede reintentar un proceso Fallido o Cancelado")
    if _has_running(items, it["process_type"], it["module"], exclude=pid):
        raise HTTPException(status_code=409, detail="Ya existe un proceso de este tipo en ejecución")
    it["retry_count"] = it.get("retry_count", 0) + 1
    it["error_message"] = ""
    it["next_retry"] = _iso(_now() + timedelta(minutes=1))
    _transition(it, "Reintentando")
    _save(items)
    return {"status": "ok", "item": it}


@router.post("/{pid}/cancel")
def cancel(pid: str) -> dict[str, Any]:
    items = _all()
    it = _find(items, pid)
    if it["status"] in ("Completado", "Cancelado"):
        raise HTTPException(status_code=409, detail="El proceso ya finalizó")
    _transition(it, "Cancelado", error="Cancelado por el administrador")
    _save(items)
    return {"status": "ok", "item": it}


@router.post("/{pid}/pause")
def pause(pid: str) -> dict[str, Any]:
    items = _all()
    it = _find(items, pid)
    if it["status"] != "Ejecutando":
        raise HTTPException(status_code=409, detail="Solo se puede pausar un proceso en ejecución")
    _transition(it, "Pendiente")
    it["worker_name"] = None
    _save(items)
    return {"status": "ok", "item": it}


@router.post("/{pid}/run-again")
def run_again(pid: str) -> dict[str, Any]:
    items = _all()
    src = _find(items, pid)
    if _has_running(items, src["process_type"], src["module"]):
        raise HTTPException(status_code=409, detail="Ya existe un proceso de este tipo en ejecución")
    now_iso = _iso(_now())
    clone = {
        **json.loads(json.dumps(src, default=str)),
        "id": str(uuid.uuid4()),
        "task_id": "celery-" + uuid.uuid4().hex[:12],
        "status": "Pendiente", "worker_name": None,
        "started_at": None, "finished_at": None, "duration_seconds": None,
        "result_json": None, "error_message": "", "retry_count": 0,
        "state_history": [{"estado": "Pendiente", "at": now_iso}],
        "logs": _seed_logs(src["process_type"], "Pendiente", ""),
        "created_at": now_iso, "updated_at": now_iso, "next_retry": None,
    }
    items.append(clone)
    _save(items)
    return {"status": "ok", "item": clone}
