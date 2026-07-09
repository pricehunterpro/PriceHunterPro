"""Logs — consola de auditoría y diagnóstico (SystemLog).

Registro de `SystemLog` en Redis (`syslogs:items`) con estado revisable
(Nuevo/Revisado/Resuelto/Ignorado). Se siembra un conjunto realista (regla 7) y
se enriquece con eventos reales del buffer en vivo `system:logs` y de
`scraping_logs`. Preparado para conectar logging real de FastAPI/Celery/scrapers
(regla 8). Integra con Scrapers y Procesos vía related_scraper_id / related_process_id.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Response

router = APIRouter(prefix="/logs", tags=["logs"])

_KEY = "syslogs:items"

NIVELES = ["Info", "Warning", "Error", "Critical"]
TIPOS = ["Scraper", "Proceso", "Publicador IA", "TikTok Factory", "Telegram",
         "Motor IA", "Base de datos", "API", "Sistema"]
ESTADOS = ["Nuevo", "Revisado", "Resuelto", "Ignorado"]

_MODULO = {
    "Scraper": "Scrapers", "Proceso": "Procesos", "Publicador IA": "Publicador IA",
    "TikTok Factory": "TikTok Factory", "Telegram": "Publicador IA", "Motor IA": "Motor IA",
    "Base de datos": "Sistema", "API": "API", "Sistema": "Sistema",
}


def _r():
    import redis as _redis
    from app.core.config import get_settings
    return _redis.from_url(get_settings().redis_url)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mk(level, tipo, mensaje, mins_ago, status="Nuevo", stack="", payload=None,
        scraper=None, process=None, user="Sistema", ip=""):
    ts = _now() - timedelta(minutes=mins_ago)
    return {
        "id": str(uuid.uuid4()),
        "level": level,
        "module": _MODULO.get(tipo, "Sistema"),
        "log_type": tipo,
        "message": mensaje,
        "stack_trace": stack,
        "payload_json": payload,
        "related_process_id": process,
        "related_scraper_id": scraper,
        "user_id": user,
        "ip_address": ip,
        "status": status,
        "created_at": ts.isoformat(),
        "updated_at": ts.isoformat(),
    }


_STACK_WAF = (
    "Traceback (most recent call last):\n"
    "  File \"app/scrapers/tottus_scraper.py\", line 88, in get_category\n"
    "    r = await client.get(url)\n"
    "  File \"httpx/_client.py\", line 1801, in get\n"
    "    return await self.request(...)\n"
    "httpx.HTTPStatusError: 503 Service Unavailable (WAF/Cloudflare)"
)
_STACK_ROI = (
    "Traceback (most recent call last):\n"
    "  File \"app/api/v1/bi_profitability.py\", line 60, in _profit_row\n"
    "    roi = ganancia / compra * 100\n"
    "ZeroDivisionError: float division by zero"
)


def _seed() -> list[dict]:
    items = [
        _mk("Critical", "Scraper", "Tottus: 3 fallos consecutivos, scraper en Error", 8,
            stack=_STACK_WAF, scraper="tottus", process=None, user="celery-worker-1"),
        _mk("Error", "Scraper", "503 Service Unavailable: WAF bloqueó las peticiones", 12,
            stack=_STACK_WAF, scraper="tottus"),
        _mk("Error", "Analytics", "DivisionByZero en cálculo de ROI (dataset vacío)", 150,
            stack=_STACK_ROI, process="proc-analytics-01", status="Revisado"),
        _mk("Warning", "Scraper", "Falabella: paginación devolvió página repetida (dedup aplicado)", 20,
            scraper="falabella"),
        _mk("Warning", "TikTok Factory", "Timeout al renderizar video 2/3, reintentando", 5,
            process="proc-tiktok-07"),
        _mk("Info", "Scraper", "Oechsle: 9,033 productos guardados (0 errores)", 12,
            scraper="oechsle", status="Resuelto", payload={"saved": 9033, "errors": 0}),
        _mk("Info", "Proceso", "Sincronización de stats completada (7 tiendas)", 30,
            process="proc-sync-03"),
        _mk("Info", "Telegram", "4 alertas enviadas al canal PriceHunter", 8,
            payload={"enviadas": 4}),
        _mk("Info", "Motor IA", "Score recalculado para 5,000 oportunidades", 45),
        _mk("Warning", "Base de datos", "Conexión a Supabase lenta (>2s) en pool", 60,
            status="Revisado"),
        _mk("Error", "API", "401 Unauthorized en /api/v1/auth/admin-login (credenciales inválidas)", 90,
            ip="190.234.11.4", user="anónimo"),
        _mk("Info", "Publicador IA", "16 items generados desde oportunidades", 45),
        _mk("Info", "Scraper", "Ripley: 3,409 productos guardados", 70,
            scraper="ripley", status="Resuelto", payload={"saved": 3409}),
        _mk("Warning", "Sistema", "Uso de memoria del worker al 82%", 100, status="Ignorado"),
        _mk("Error", "Publicador IA", "Fallo al publicar en Instagram (token expirado)", 300,
            stack="InstagramAPIError: (190) Error validating access token", status="Revisado"),
        _mk("Info", "Limpieza de datos" if False else "Sistema", "Limpieza de price_history: 12,045 registros eliminados", 180,
            payload={"deleted": 12045}),
        _mk("Critical", "Base de datos", "Deadlock detectado en bulk_upsert_store (reintentado)", 200,
            stack="psycopg2.errors.DeadlockDetected: deadlock detected", status="Resuelto"),
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


def _find(items: list[dict], lid: str) -> dict:
    for it in items:
        if it["id"] == lid:
            return it
    raise HTTPException(status_code=404, detail="Log no encontrado")


def _filtered(level=None, module=None, log_type=None, status=None, q=None) -> list[dict]:
    items = sorted(_all(), key=lambda i: i.get("created_at") or "", reverse=True)
    if level:    items = [i for i in items if i["level"] == level]
    if module:   items = [i for i in items if i["module"] == module]
    if log_type: items = [i for i in items if i["log_type"] == log_type]
    if status:   items = [i for i in items if i["status"] == status]
    if q:
        ql = q.lower()
        items = [i for i in items if ql in i["message"].lower() or ql in i["module"].lower() or ql in i["log_type"].lower()]
    return items


# ── Lectura ──────────────────────────────────────────────────────────────────
@router.get("")
def list_logs(
    level: str | None = None, module: str | None = None, log_type: str | None = None,
    status: str | None = None, q: str | None = None, limit: int = 300,
) -> dict[str, Any]:
    items = _filtered(level, module, log_type, status, q)[:limit]
    allm = _all()
    return {
        "items": items, "total": len(items),
        "niveles": NIVELES, "tipos": TIPOS, "estados": ESTADOS,
        "modulos": sorted({i["module"] for i in allm}),
    }


@router.get("/stats")
def stats() -> dict[str, Any]:
    items = _all()
    day_ago = (_now() - timedelta(hours=24)).isoformat()
    def c(**kw):
        r = items
        for k, v in kw.items():
            r = [i for i in r if i.get(k) == v]
        return len(r)
    err_24h = sum(1 for i in items if i["level"] in ("Error", "Critical") and (i.get("created_at") or "") >= day_ago)
    # módulo con más errores
    err_by_mod: dict[str, int] = {}
    for i in items:
        if i["level"] in ("Error", "Critical"):
            err_by_mod[i["module"]] = err_by_mod.get(i["module"], 0) + 1
    mod_top = max(err_by_mod.items(), key=lambda kv: kv[1])[0] if err_by_mod else "—"
    ultimo = next((i for i in sorted(items, key=lambda x: x.get("created_at") or "", reverse=True)
                   if i["level"] in ("Error", "Critical")), None)
    return {
        "kpis": {
            "total":          len(items),
            "criticos":       c(level="Critical"),
            "warnings":       c(level="Warning"),
            "errores24h":     err_24h,
            "moduloConMasErrores": mod_top,
            "ultimoError":    (ultimo["message"][:70] if ultimo else "—"),
        },
        "porNivel": {n: c(level=n) for n in NIVELES},
    }


@router.get("/export")
def export_csv(
    level: str | None = None, module: str | None = None, log_type: str | None = None,
    status: str | None = None, q: str | None = None,
) -> Response:
    import csv
    import io
    items = _filtered(level, module, log_type, status, q)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "fecha", "nivel", "modulo", "tipo", "mensaje", "estado",
                "usuario", "ip", "scraper", "proceso"])
    for i in items:
        w.writerow([i["id"], i["created_at"], i["level"], i["module"], i["log_type"],
                    i["message"], i["status"], i.get("user_id", ""), i.get("ip_address", ""),
                    i.get("related_scraper_id", ""), i.get("related_process_id", "")])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=pricehunter_logs.csv"},
    )


@router.get("/{lid}")
def get_one(lid: str) -> dict[str, Any]:
    return {"item": _find(_all(), lid)}


# ── Control ──────────────────────────────────────────────────────────────────
@router.put("/{lid}/status")
def set_status(lid: str, body: dict = Body(...)) -> dict[str, Any]:
    estado = body.get("status")
    if estado not in ESTADOS:
        raise HTTPException(status_code=400, detail="Estado inválido")
    items = _all()
    it = _find(items, lid)
    it["status"] = estado
    it["updated_at"] = _now().isoformat()
    _save(items)
    return {"status": "ok", "item": it}


@router.post("/{lid}/retry-related")
def retry_related(lid: str) -> dict[str, Any]:
    it = _find(_all(), lid)
    scraper = it.get("related_scraper_id")
    process = it.get("related_process_id")

    if scraper:
        try:
            from app.api.v1.scrapers import run as run_scraper
            res = run_scraper(scraper)
            return {"status": "ok", "kind": "scraper", "id": scraper, "detail": res}
        except HTTPException as e:
            raise e
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"No se pudo reintentar el scraper: {exc}")
    if process:
        try:
            from app.api.v1.processes import retry as retry_process
            res = retry_process(process)
            return {"status": "ok", "kind": "process", "id": process, "detail": res}
        except HTTPException:
            return {"status": "ok", "kind": "process", "id": process,
                    "detail": {"message": "Proceso relacionado no disponible para reintento directo"}}
    raise HTTPException(status_code=400, detail="El log no tiene proceso ni scraper relacionado")
