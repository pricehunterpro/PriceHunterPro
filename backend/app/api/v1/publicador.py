"""Publicador IA.

Gestiona contenido generado por IA para múltiples canales:
Telegram, Facebook, Instagram, TikTok.

Flujo: Pendiente → Generar → Generado → Aprobar → Aprobado → Publicar → Publicado
       Aprobado → Programar → Programado → Publicar → Publicado

Regla: NADA se publica automáticamente; publicar requiere acción manual.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException

router = APIRouter(prefix="/publicador", tags=["publicador"])

_REDIS_KEY = "publicador:items"
_REFRESH_KEY = "publicador:items:refreshed_at"

# Cuantos items sirve el panel.
_TOTAL_ITEMS = 16

# Items que NO se tocan al refrescar: representan trabajo del administrador.
# Solo se reemplazan los "Pendiente", que son las tarjetas que nadie abrio.
_ESTADOS_CON_TRABAJO = {"Generado", "Aprobado", "Programado", "Publicado", "Error"}

# "Publicado" es trabajo TERMINADO: el mensaje ya salio al canal y su registro
# vive en el Calendario Editorial. Si se conservan para siempre terminan
# ocupando todas las tarjetas y el panel deja de refrescarse — que es
# exactamente el sintoma que se venia a corregir. Se retiran por antiguedad.
_ESTADO_TERMINADO = "Publicado"

ESTADOS = ["Pendiente", "Generado", "Aprobado", "Programado", "Publicado", "Error"]
CANALES = ["Telegram", "Facebook", "Instagram", "TikTok"]

_STORE_TAGS: dict[str, str] = {
    "falabella": "#Falabella", "ripley": "#Ripley", "plazavea": "#PlazaVea",
    "oechsle": "#Oechsle", "sodimac": "#Sodimac", "estilos": "#Estilos",
    "shopstar": "#Shopstar",
}


def _r():
    import redis as _redis
    from app.core.config import get_settings
    return _redis.from_url(get_settings().redis_url)


def _all_items() -> list[dict]:
    raw = _r().get(_REDIS_KEY) or b"[]"
    return json.loads(raw)


def _save_items(items: list[dict]) -> None:
    _r().set(_REDIS_KEY, json.dumps(items, default=str))


def _hashtags(store: str, category: str, disc: int) -> list[str]:
    cat_slug = (category or "general").lower().replace(" ", "").replace("/", "")
    tags = ["#ofertasperu", "#pricehunterpro", "#descuentos", "#peru"]
    tags.append(_STORE_TAGS.get(store, f"#{store.capitalize()}"))
    if disc >= 50:
        tags.append("#megaoferta")
    elif disc >= 30:
        tags.append("#superoferta")
    tags.append(f"#{cat_slug}")
    return tags


def _generar_contenido(
    canal: str, name: str, store: str, category: str,
    current: float, original: float, disc: int, url: str,
) -> str:
    # Copy estilo SUPERCUPON: el TITULAR es el PRODUCTO + PRECIO FINAL (lo que
    # engancha: "iPhone 17e a S/599"), no el "% OFF DETECTADO". El precio tachado
    # y el % quedan de refuerzo, debajo.
    from app.services.deal_ranker import titular
    cat_slug = (category or "general").lower()
    gancho = titular(name, current, disc)          # "🔥 {Producto} a solo S/ X"
    hashtags_line = " ".join(_hashtags(store, category, disc))

    if canal == "Telegram":
        return (
            f"{gancho}\n\n"
            f"~~S/{original:.2f}~~ → **S/{current:.2f}**  ·  **-{disc}%**\n"
            f"🏪 {store.capitalize()} | 📂 {cat_slug.capitalize()}\n"
            f"👉 Link en este mensaje 👇\n\n"
            f"{hashtags_line}"
        )
    if canal == "Instagram":
        return (
            f"{gancho}\n\n"
            f"Antes S/{original:.2f} → AHORA S/{current:.2f}  (-{disc}%)\n"
            f"📍 {store.capitalize()} | {cat_slug.capitalize()}\n"
            f"👉 Link en bio 🔗\n\n"
            f"{hashtags_line} #instagram"
        )
    if canal == "TikTok":
        return (
            f"{gancho}\n\n"
            f"Antes S/{original:.2f} → AHORA S/{current:.2f}  (-{disc}%)\n"
            f"Tienda: {store.capitalize()} 🛒\n"
            f"👉 Link en bio 👇\n\n"
            f"{hashtags_line} #tiktok #fyp #viral"
        )
    # Facebook
    return (
        f"{gancho}\n\n"
        f"💰 Antes S/{original:.2f} → AHORA S/{current:.2f}  (-{disc}%)\n"
        f"🏪 Disponible en {store.capitalize()}\n"
        f"👉 Link en los comentarios 👇\n\n"
        f"{hashtags_line}"
    )


def _seed_items() -> list[dict]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.core.config import get_settings
    from app.services.deal_ranker import fetch_candidates, seleccionar_top

    db_url = (
        get_settings().database_url
        .replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    )
    engine = create_engine(db_url)
    # Selección estilo SUPERCUPON (app.services.deal_ranker): variedad por tramo
    # de precio + marcas deseables + precio alcanzable primero, descartando basura
    # (genéricos, "Lentes" spam) y deduplicando por nombre. Reemplaza el viejo
    # "top-16 por descuento" que se llenaba de iluminación con original corrupto.
    with Session(engine) as session:
        candidatos = fetch_candidates(session)
    rows = seleccionar_top(candidatos, total=16)

    estados_init = [
        "Pendiente", "Generado",  "Programado", "Publicado",
        "Aprobado",  "Programado", "Publicado",  "Programado",
        "Pendiente", "Error",     "Programado",  "Publicado",
        "Generado",  "Programado", "Publicado",  "Programado",
    ]
    scores = [95, 88, 92, 80, 87, 76, 83, 91, 70, 55, 78, 85, 93, 68, 82, 79]
    canales_sets = [
        ["Telegram", "Facebook"],
        ["Telegram", "Instagram"],
        ["Facebook", "Instagram"],
        ["TikTok"],
        ["Telegram"],
        ["Facebook", "TikTok"],
        ["Instagram", "TikTok"],
        ["Telegram", "Facebook", "Instagram"],
        ["Telegram"],
        ["Facebook"],
        ["Instagram"],
        ["TikTok", "Telegram"],
        ["Facebook", "Instagram", "TikTok"],
        ["Telegram", "Facebook"],
        ["Instagram"],
        ["TikTok"],
    ]

    items: list[dict] = []
    for i, row in enumerate(rows):
        disc = int(row.get("discountPct") or 0)
        cp = float(row.get("currentPrice") or 0)
        op = float(row.get("originalPrice") or 0)
        name = row.get("name") or ""
        store = row.get("store") or ""
        category = row.get("category") or "General"
        canales_sel = canales_sets[i % len(canales_sets)]
        estado = estados_init[i % len(estados_init)]
        has_content = estado not in ("Pendiente", "Error")
        contenido = (
            _generar_contenido(
                canales_sel[0], name, store, category,
                cp, op, disc, row.get("url") or "",
            )
            if has_content else ""
        )
        # Fechas para el Calendario Editorial: Programado → futuro, Publicado → pasado
        now = datetime.now(timezone.utc)
        fecha_prog = None
        fecha_pub = None
        created = now
        if estado == "Programado":
            fecha_prog = (now + timedelta(days=(i % 18), hours=9 + (i % 8))).isoformat()
        elif estado == "Publicado":
            fecha_pub = (now - timedelta(days=1 + (i % 20), hours=(i % 12))).isoformat()
        else:
            created = now - timedelta(days=(i % 6), hours=(i % 10))
        items.append({
            "id":                   str(uuid.uuid4()),
            "opportunityId":        str(row.get("id", "")),
            "titulo":               name[:70],
            "store":                store,
            "category":             category,
            "currentPrice":         cp,
            "originalPrice":        op,
            "discountPct":          disc,
            "imageUrl":             row.get("imageUrl") or "",
            "url":                  row.get("url") or "",
            "canalesSeleccionados": canales_sel,
            "contenido":            contenido,
            "hashtags":             _hashtags(store, category, disc),
            "scoreIA":              scores[i % len(scores)],
            "estado":               estado,
            "fechaProgramada":      fecha_prog,
            "fechaPublicacion":     fecha_pub,
            "generadoAt":           None if not has_content else now.isoformat(),
            "createdAt":            created.isoformat(),
        })

    _save_items(items)
    return items


def _norm_nombre(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _fecha(valor: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(valor))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _conservar(items: list[dict], ahora: datetime, dias_publicados: float) -> list[dict]:
    """Items que sobreviven al refresco.

    Todo lo que tiene trabajo pendiente se queda. Lo ya PUBLICADO se queda solo
    mientras sea reciente: si no, el panel se llena de publicaciones viejas y no
    entra contenido nuevo.
    """
    out: list[dict] = []
    for i in items:
        estado = i.get("estado")
        if estado not in _ESTADOS_CON_TRABAJO:
            continue
        if estado == _ESTADO_TERMINADO and dias_publicados > 0:
            fecha = _fecha(i.get("fechaPublicacion")) or _fecha(i.get("createdAt"))
            if fecha and (ahora - fecha) > timedelta(days=dias_publicados):
                continue          # publicacion antigua: libera la tarjeta
        out.append(i)
    return out


def _item_pendiente(row: dict, ahora: datetime) -> dict:
    """Arma una tarjeta NUEVA, siempre en Pendiente.

    A diferencia del seed inicial (que reparte estados y fechas para poblar la
    demo), lo que entra por refresco es contenido real recien detectado: nace
    Pendiente y el administrador decide si lo genera y publica.
    """
    disc = int(row.get("discountPct") or 0)
    store = row.get("store") or ""
    category = row.get("category") or "General"
    return {
        "id": str(uuid.uuid4()),
        "opportunityId": str(row.get("id", "")),
        "titulo": (row.get("name") or "")[:70],
        "store": store,
        "category": category,
        "currentPrice": float(row.get("currentPrice") or 0),
        "originalPrice": float(row.get("originalPrice") or 0),
        "discountPct": disc,
        "imageUrl": row.get("imageUrl") or "",
        "url": row.get("url") or "",
        "canalesSeleccionados": ["Telegram"],
        "contenido": "",
        "hashtags": _hashtags(store, category, disc),
        "scoreIA": 0,
        "estado": "Pendiente",
        "fechaProgramada": None,
        "fechaPublicacion": None,
        "generadoAt": None,
        "createdAt": ahora.isoformat(),
        "origen": "Refresco automatico",
    }


def _refrescar_si_toca(items: list[dict]) -> list[dict]:
    """Renueva las tarjetas Pendiente con los candidatos actuales.

    El panel se sembraba UNA sola vez y quedaba congelado: `get_items` solo
    llamaba al seed con la lista vacia, asi que despues de la primera carga
    seguia mostrando el mismo lote durante semanas, generado ademas con el
    ranking viejo (iluminacion con precio de lista corrupto y duplicados).

    Se reconcilia en vez de borrar, igual que `stores._all` y `scrapers._all`:
    lo que tiene estado se conserva y solo se reemplaza lo que nadie abrio.
    """
    from app.services.settings_service import get_setting

    horas = float(get_setting("publicaciones", "refresco_horas", 12) or 0)
    if horas <= 0:
        return items          # 0 = refresco automatico desactivado

    r = _r()
    ahora = datetime.now(timezone.utc)
    ultimo = r.get(_REFRESH_KEY)
    if ultimo:
        try:
            ts = datetime.fromisoformat(ultimo.decode())
            if (ahora - ts) < timedelta(hours=horas):
                return items
        except Exception:
            pass

    dias = float(get_setting("publicaciones", "retencion_publicados_dias", 7) or 0)
    conservados = _conservar(items, ahora, dias)
    try:
        nuevos = _candidatos_nuevos(conservados, ahora)
    except Exception:
        # Si la BD no responde, se sirve la lista actual: mejor contenido viejo
        # que un panel vacio.
        return items

    resultado = conservados + nuevos
    _save_items(resultado)
    r.set(_REFRESH_KEY, ahora.isoformat())
    return resultado


def _candidatos_nuevos(conservados: list[dict], ahora: datetime) -> list[dict]:
    """Candidatos frescos para llenar las tarjetas que quedaron libres."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.core.config import get_settings
    from app.services.deal_ranker import fetch_candidates, seleccionar_top

    faltan = _TOTAL_ITEMS - len(conservados)
    if faltan <= 0:
        return []

    engine = create_engine(
        get_settings().database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    )
    with Session(engine) as session:
        candidatos = fetch_candidates(session)

    # Se pide de mas porque hay que descartar los que ya estan en el panel.
    seleccion = seleccionar_top(candidatos, total=_TOTAL_ITEMS + len(conservados))

    vistos = {_norm_nombre(i.get("titulo")) for i in conservados}
    ids = {str(i.get("opportunityId")) for i in conservados}
    nuevos: list[dict] = []
    for d in seleccion:
        if len(nuevos) >= faltan:
            break
        nombre = _norm_nombre(d.get("name"))
        if nombre in vistos or str(d.get("id")) in ids:
            continue
        vistos.add(nombre)
        ids.add(str(d.get("id")))
        nuevos.append(_item_pendiente(d, ahora))
    return nuevos


def _kpis(items: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {e: 0 for e in ESTADOS}
    for it in items:
        e = it.get("estado", "Pendiente")
        counts[e] = counts.get(e, 0) + 1
    return {
        "total":       len(items),
        "pendientes":  counts["Pendiente"],
        "generados":   counts["Generado"],
        "aprobados":   counts["Aprobado"],
        "programados": counts["Programado"],
        "publicados":  counts["Publicado"],
        "errores":     counts["Error"],
    }


def _find(items: list[dict], item_id: str) -> dict:
    for it in items:
        if it["id"] == item_id:
            return it
    raise HTTPException(status_code=404, detail="Item no encontrado")


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/items")
def get_items(estado: str | None = None, canal: str | None = None) -> dict[str, Any]:
    items = _all_items()
    if not items:
        items = _seed_items()
    else:
        items = _refrescar_si_toca(items)
    filtered = items
    if estado:
        filtered = [i for i in filtered if i.get("estado") == estado]
    if canal:
        filtered = [i for i in filtered if canal in i.get("canalesSeleccionados", [])]
    return {"items": filtered, "kpis": _kpis(items), "canales": CANALES, "estados": ESTADOS}


@router.post("/generar")
def generar(body: dict = Body(...)) -> dict[str, Any]:
    """Genera contenido IA para el item: Pendiente/Error → Generado."""
    items = _all_items()
    it = _find(items, body.get("id", ""))
    if it["estado"] not in ("Pendiente", "Error"):
        raise HTTPException(status_code=409, detail="Solo se puede generar para items Pendiente o Error")
    canales_sel = it.get("canalesSeleccionados") or ["Telegram"]
    canal_primary = canales_sel[0]
    it["contenido"] = _generar_contenido(
        canal_primary, it["titulo"], it["store"], it.get("category", "General"),
        it["currentPrice"], it["originalPrice"], it["discountPct"], it.get("url", ""),
    )
    it["hashtags"] = _hashtags(it["store"], it.get("category", "General"), it["discountPct"])
    it["estado"] = "Generado"
    it["generadoAt"] = datetime.now(timezone.utc).isoformat()
    _save_items(items)
    return {"status": "ok", "estado": "Generado", "item": it}


@router.post("/aprobar")
def aprobar(body: dict = Body(...)) -> dict[str, str]:
    items = _all_items()
    it = _find(items, body.get("id", ""))
    if it["estado"] != "Generado":
        raise HTTPException(status_code=409, detail="Solo se puede aprobar un item Generado")
    it["estado"] = "Aprobado"
    _save_items(items)
    return {"status": "ok", "estado": "Aprobado"}


@router.post("/programar")
def programar(body: dict = Body(...)) -> dict[str, str]:
    items = _all_items()
    it = _find(items, body.get("id", ""))
    fecha = body.get("fecha", "")
    if not fecha:
        raise HTTPException(status_code=400, detail="Falta la fecha de programación")
    it["estado"] = "Programado"
    it["fechaProgramada"] = fecha
    _save_items(items)
    return {"status": "ok", "estado": "Programado", "fecha": fecha}


@router.post("/publicar")
def publicar(body: dict = Body(...)) -> dict[str, str]:
    """Publica manualmente. Solo si está Aprobado o Programado."""
    items = _all_items()
    it = _find(items, body.get("id", ""))
    if it["estado"] not in ("Aprobado", "Programado"):
        raise HTTPException(
            status_code=409,
            detail="Solo se puede publicar un item Aprobado o Programado",
        )
    it["estado"] = "Publicado"
    it["fechaPublicacion"] = datetime.now(timezone.utc).isoformat()
    _save_items(items)
    return {"status": "ok", "estado": "Publicado"}


@router.post("/update")
def update(body: dict = Body(...)) -> dict[str, Any]:
    """Editar contenido, hashtags o canales seleccionados."""
    items = _all_items()
    it = _find(items, body.get("id", ""))
    if "titulo" in body:
        it["titulo"] = str(body["titulo"])[:70]
    if "contenido" in body:
        it["contenido"] = str(body["contenido"])
    if "hashtags" in body and isinstance(body["hashtags"], list):
        it["hashtags"] = [str(h) for h in body["hashtags"]]
    if "canalesSeleccionados" in body and isinstance(body["canalesSeleccionados"], list):
        it["canalesSeleccionados"] = [str(c) for c in body["canalesSeleccionados"]]
    if it["estado"] == "Error":
        it["estado"] = "Generado"
    _save_items(items)
    return {"status": "ok", "item": it}


@router.post("/reload")
def reload_items(full: bool = False) -> dict[str, Any]:
    """Recarga los items desde la BD.

    Por defecto CONSERVA lo que ya tiene trabajo encima (generado, aprobado,
    programado, publicado) y solo renueva las tarjetas Pendiente. Antes borraba
    la lista entera, con lo que un clic en "Recargar desde BD" se llevaba por
    delante el historial de publicaciones.

    `full=true` mantiene el comportamiento destructivo, para cuando de verdad se
    quiere empezar de cero.
    """
    r = _r()
    if full:
        r.delete(_REDIS_KEY)
        r.delete(_REFRESH_KEY)
        items = _seed_items()
        return {"status": "ok", "count": len(items), "conservados": 0, "modo": "completo"}

    from app.services.settings_service import get_setting

    ahora = datetime.now(timezone.utc)
    actuales = _all_items()
    if not actuales:
        items = _seed_items()
        r.set(_REFRESH_KEY, ahora.isoformat())
        return {"status": "ok", "count": len(items), "conservados": 0, "modo": "inicial"}

    dias = float(get_setting("publicaciones", "retencion_publicados_dias", 7) or 0)
    conservados = _conservar(actuales, ahora, dias)
    nuevos = _candidatos_nuevos(conservados, ahora)
    items = conservados + nuevos
    _save_items(items)
    r.set(_REFRESH_KEY, ahora.isoformat())
    return {
        "status": "ok", "count": len(items),
        "conservados": len(conservados), "nuevos": len(nuevos), "modo": "reconciliado",
    }


# ── Calendario Editorial ────────────────────────────────────────────────────

# Estados del calendario (4). Los estados internos Generado/Aprobado se agrupan
# como "Pendiente" (contenido listo pero aún sin programar/publicar).
CAL_ESTADOS = ["Publicado", "Programado", "Pendiente", "Error"]


def _cal_estado(estado: str) -> str:
    if estado in ("Publicado", "Programado", "Error"):
        return estado
    return "Pendiente"  # Pendiente, Generado, Aprobado


def _cal_fecha(it: dict) -> str | None:
    """Fecha en la que el item cae en el calendario según su estado."""
    if it.get("estado") == "Publicado" and it.get("fechaPublicacion"):
        return it["fechaPublicacion"]
    if it.get("estado") == "Programado" and it.get("fechaProgramada"):
        return it["fechaProgramada"]
    return it.get("fechaProgramada") or it.get("fechaPublicacion") or it.get("createdAt")


@router.get("/calendario")
def calendario() -> dict[str, Any]:
    """Eventos para el Calendario Editorial, integrados con el Publicador IA.
    Reutiliza los mismos items (Redis): cada uno se ubica en una fecha según su
    estado y se mapea a uno de los 4 estados del calendario."""
    items = _all_items()
    if not items:
        items = _seed_items()

    eventos = []
    kpis = {e: 0 for e in CAL_ESTADOS}
    for it in items:
        cal_estado = _cal_estado(it.get("estado", "Pendiente"))
        kpis[cal_estado] += 1
        eventos.append({
            "id":          it["id"],
            "titulo":      it.get("titulo", ""),
            "store":       it.get("store", ""),
            "category":    it.get("category", ""),
            "discountPct": it.get("discountPct", 0),
            "currentPrice": it.get("currentPrice", 0),
            "imageUrl":    it.get("imageUrl", ""),
            "canales":     it.get("canalesSeleccionados", []),
            "estado":      cal_estado,
            "estadoReal":  it.get("estado", "Pendiente"),
            "fecha":       _cal_fecha(it),
        })

    return {"eventos": eventos, "kpis": kpis, "estados": CAL_ESTADOS, "total": len(eventos)}
