"""Motor de Recomendaciones IA.

Decide QUÉ HACER con cada oportunidad: comprarla, publicarla, revisarla o
ignorarla. NO calcula un score propio — reutiliza las piezas que ya existen:

    - `app.ai.scorer.calculate_score`  → PriceHunter Score (Motor IA)
    - `app.services.deal_ranker`       → viralidad estilo SUPERCUPON
                                         (marca deseable, precio alcanzable, basura)
    - `app.services.deal_service`      → precio actual, mediana histórica, margen
    - agregación por categoría         → misma idea que Tendencias IA (`ai_trends._agg`)

Este módulo es solo la CAPA DE DECISIÓN sobre esos insumos. Si mañana entra una
IA avanzada (LLM/modelo entrenado), reemplaza `_decidir()` y el resto sigue igual.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.services.deal_ranker import es_basura, marca_es_deseable
from app.services.deal_ranker import score as viral_score

# ── Vocabulario del módulo ───────────────────────────────────────────────────
TIPOS = [
    "Comprar",
    "Publicar",
    "Comprar y Publicar",
    "Revisar",
    "Ignorar",
    "Enviar a TikTok Factory",
    "Enviar a Publicador IA",
]
PRIORIDADES = ["Alta", "Media", "Baja"]
ESTADOS = ["Nueva", "Revisada", "Enviada a Publicador", "Enviada a TikTok", "Ignorada"]

# Tipos que cuentan como "recomendación de compra" / "de publicación" en los KPIs.
TIPOS_COMPRA = {"Comprar", "Comprar y Publicar"}
TIPOS_PUBLICACION = {
    "Publicar", "Comprar y Publicar", "Enviar a TikTok Factory", "Enviar a Publicador IA",
}

# ── Umbrales de decisión ─────────────────────────────────────────────────────
# El ROI estimado es `marginPct` de DealService: (original - actual) / actual, o sea
# cuánto se gana revendiendo al precio de lista. Es una ESTIMACIÓN, no un margen real.
_ROI_COMPRA = 35.0          # ROI mínimo para que valga la pena comprar para revender
# ROI por encima del cual el número deja de ser creíble: implica un precio de lista
# >4x el actual, que en este catálogo casi siempre es original inflado o mal parseado
# (el mismo problema que ya filtran deal_service y deal_ranker). No se recomienda
# comprar a ciegas con esa cifra: se manda a revisar.
_ROI_SOSPECHOSO = 300.0
_SCORE_COMPRA = 65          # score mínimo para recomendar compra
_SCORE_PUBLICAR = 60        # score mínimo para recomendar publicación
_SCORE_REVISAR = 45         # por debajo de esto ya no se revisa: se ignora
_PRECIO_ALCANZABLE = 1000   # S/ — por encima, el producto deja de ser de impulso

# Mínimo de ofertas para que el promedio de una categoría sea representativo.
_MIN_MUESTRA_CATEGORIA = 5


def contexto_categorias(scored: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Descuento y score promedio por categoría (tendencia de mercado).

    Es la misma agregación que usa Tendencias IA; sirve para responder "¿este
    descuento es bueno PARA SU CATEGORÍA?" en lugar de compararlo contra todo el
    catálogo, donde una laptop al 25% y un polo al 25% no son comparables.
    """
    grupos: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in scored:
        cat = (d.get("category") or "").strip()
        if cat:
            grupos[cat].append(d)

    out: dict[str, dict[str, float]] = {}
    for cat, ds in grupos.items():
        n = len(ds)
        if n < _MIN_MUESTRA_CATEGORIA:
            continue
        out[cat] = {
            "descuentoPromedio": round(sum(x["discountPct"] for x in ds) / n, 1),
            "scorePromedio": round(sum(x["score"] for x in ds) / n, 1),
            "ofertas": n,
        }
    return out


def _percentil(valores: list[float], p: float) -> float:
    if not valores:
        return 0.0
    orden = sorted(valores)
    idx = min(len(orden) - 1, max(0, int(round((len(orden) - 1) * p))))
    return orden[idx]


def _decidir(
    deal: dict[str, Any],
    viralidad: float,
    disc_cat: float,
    umbral_viral_alto: float,
    umbral_viral_medio: float,
) -> tuple[str, str, list[str]]:
    """Devuelve (tipo, prioridad, evidencias).

    Las evidencias son frases sueltas con el dato concreto que las respalda; el
    motivo final se arma con ellas en `_motivo()`.
    """
    score = int(deal.get("score") or 0)
    roi = float(deal.get("marginPct") or 0)
    disc = float(deal.get("discountPct") or 0)
    precio = float(deal.get("currentPrice") or 0)
    below = bool(deal.get("belowMarket"))
    mkt_diff = float(deal.get("mktDiffPct") or 0)
    in_stock = bool(deal.get("inStock", True))
    deseable = marca_es_deseable(deal.get("name"), deal.get("brand"))

    ev: list[str] = []
    if score >= 80:
        ev.append(f"score alto ({score}/100)")
    elif score >= 60:
        ev.append(f"score competitivo ({score}/100)")
    else:
        ev.append(f"score bajo ({score}/100)")

    if disc_cat > 0 and disc > disc_cat:
        ev.append(f"descuento {disc:.0f}% por encima del promedio de su categoría ({disc_cat:.0f}%)")
    elif disc >= 40:
        ev.append(f"descuento {disc:.0f}%")

    if below and mkt_diff > 0:
        ev.append(f"precio {mkt_diff:.0f}% bajo su mediana histórica")
    if roi >= _ROI_COMPRA:
        ev.append(f"ROI estimado {roi:.0f}%")
    if deseable:
        ev.append("marca reconocible")
    if precio < _PRECIO_ALCANZABLE:
        ev.append(f"precio alcanzable (S/ {precio:,.0f})")

    # ── Descartes duros ──────────────────────────────────────────────────────
    # `es_basura` es el mismo filtro del Publicador (revendedor genérico o
    # categoría spam): si no sirve para publicar, tampoco para recomendar.
    if es_basura(deal.get("name"), deal.get("brand"), deal.get("category")):
        return "Ignorar", "Baja", ["marca genérica o categoría descartada por el filtro del Publicador"]
    if not in_stock:
        return "Ignorar", "Baja", ["sin stock"]
    if score < _SCORE_REVISAR:
        return "Ignorar", "Baja", ev
    if roi > _ROI_SOSPECHOSO:
        return "Revisar", "Media", [
            f"ROI estimado de {roi:.0f}% poco creíble (precio de lista probablemente inflado)",
            f"descuento {disc:.0f}%",
            f"score {score}/100",
        ]

    # ── Señales independientes ───────────────────────────────────────────────
    compra_ok = score >= _SCORE_COMPRA and roi >= _ROI_COMPRA
    publica_ok = score >= _SCORE_PUBLICAR and (
        viralidad >= umbral_viral_medio or (deseable and disc_cat > 0 and disc > disc_cat)
    )

    if compra_ok and publica_ok:
        prioridad = "Alta" if (below or score >= 80) else "Media"
        return "Comprar y Publicar", prioridad, ev
    if compra_ok:
        # Comprar de verdad exige que el precio esté bajo su propio histórico: sin
        # eso, el "descuento" puede ser solo un precio de lista inflado.
        prioridad = "Alta" if below and score >= 75 else "Media"
        return "Comprar", prioridad, ev
    if publica_ok:
        if viralidad >= umbral_viral_alto and deal.get("imageUrl"):
            # TikTok necesita imagen: sin foto no hay video que generar.
            return "Enviar a TikTok Factory", "Alta", ev
        if deseable and precio < _PRECIO_ALCANZABLE:
            return "Enviar a Publicador IA", "Alta" if score >= 75 else "Media", ev
        return "Publicar", "Media", ev
    if score >= _SCORE_REVISAR:
        return "Revisar", "Media" if score >= 55 else "Baja", ev
    return "Ignorar", "Baja", ev


_PLANTILLA_MOTIVO = {
    "Comprar": "Se recomienda comprar porque",
    "Publicar": "Se recomienda publicar porque",
    "Comprar y Publicar": "Se recomienda comprar y publicar porque",
    "Revisar": "Se recomienda revisar porque",
    "Ignorar": "Se recomienda ignorar porque",
    "Enviar a TikTok Factory": "Se recomienda enviar a TikTok Factory porque",
    "Enviar a Publicador IA": "Se recomienda enviar a Publicador IA porque",
}


def _motivo(tipo: str, evidencias: list[str]) -> str:
    prefijo = _PLANTILLA_MOTIVO.get(tipo, "Se recomienda revisar porque")
    partes = evidencias[:3] or ["no hay señales suficientes"]
    if len(partes) == 1:
        cuerpo = partes[0]
    else:
        cuerpo = ", ".join(partes[:-1]) + " y " + partes[-1]
    return f"{prefijo} tiene {cuerpo}."


def build_recommendations(scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convierte oportunidades YA puntuadas por el Motor IA en recomendaciones.

    `scored` = items de `DealService.get_deals()` enriquecidos con
    `calculate_score()` (score, clasificacion, explicacion).
    """
    contexto = contexto_categorias(scored)

    # Viralidad: puntaje SUPERCUPON de `deal_ranker.score` (marca deseable +
    # precio alcanzable + descuento). Se normaliza a 0-100 con el máximo del lote
    # para que sea comparable entre corridas.
    virales = [viral_score(d) for d in scored]
    vmax = max(virales) if virales else 1.0
    umbral_alto = _percentil(virales, 0.90)
    umbral_medio = _percentil(virales, 0.70)

    # Posición en el Ranking IA (mismo criterio que /ai/ranking: score desc).
    posiciones = {
        d["id"]: i + 1
        for i, d in enumerate(sorted(scored, key=lambda x: x["score"], reverse=True))
    }

    recs: list[dict[str, Any]] = []
    for deal, viral in zip(scored, virales):
        cat = (deal.get("category") or "").strip()
        disc_cat = contexto.get(cat, {}).get("descuentoPromedio", 0.0)
        tipo, prioridad, evidencias = _decidir(
            deal, viral, disc_cat, umbral_alto, umbral_medio,
        )
        recs.append({
            # ── Modelo AIRecommendation ──
            "id": f"rec-{deal['id']}",
            "opportunity_id": str(deal["id"]),
            "product_name": deal.get("name") or "",
            "store": deal.get("store") or "",
            "category": cat or "General",
            "brand": deal.get("brand") or "",
            "current_price": round(float(deal.get("currentPrice") or 0), 2),
            "historical_price": round(float(deal.get("avgMarketPrice") or 0), 2),
            "discount_percent": round(float(deal.get("discountPct") or 0), 1),
            "estimated_margin": round(float(deal.get("marginPct") or 0), 1),
            "pricehunter_score": int(deal.get("score") or 0),
            "recommendation_type": tipo,
            "priority": prioridad,
            "reason": _motivo(tipo, evidencias),
            "status": "Nueva",                       # lo sobreescribe el overlay de Redis
            "created_at": deal.get("scrapedAt") or "",
            "updated_at": deal.get("scrapedAt") or "",
            # ── Contexto para la vista (no forma parte del modelo persistido) ──
            "clasificacion": deal.get("clasificacion") or "",
            "viralidad": round(viral / vmax * 100, 1) if vmax else 0.0,
            "ranking_pos": posiciones.get(deal["id"], 0),
            "category_avg_discount": disc_cat,
            "below_market": bool(deal.get("belowMarket")),
            "mkt_diff_pct": round(float(deal.get("mktDiffPct") or 0), 1),
            "in_stock": bool(deal.get("inStock", True)),
            "original_price": round(float(deal.get("originalPrice") or 0), 2),
            "image_url": deal.get("imageUrl") or "",
            "url": deal.get("url") or "",
        })
    return recs


def kpis(recs: list[dict[str, Any]]) -> dict[str, Any]:
    """KPIs del módulo. `recs` ya viene filtrado por la vista."""
    total = len(recs)
    compra = [r for r in recs if r["recommendation_type"] in TIPOS_COMPRA]
    publicacion = [r for r in recs if r["recommendation_type"] in TIPOS_PUBLICACION]
    revision = [r for r in recs if r["recommendation_type"] == "Revisar"]
    accionables = [r for r in recs if r["recommendation_type"] != "Ignorar"]

    avg_score = (
        round(sum(r["pricehunter_score"] for r in accionables) / len(accionables), 1)
        if accionables else 0.0
    )
    # El ROI promedio se mide sobre las de COMPRA: es donde el número significa algo.
    avg_roi = (
        round(sum(r["estimated_margin"] for r in compra) / len(compra), 1)
        if compra else 0.0
    )
    return {
        "recomendacionesGeneradas": total,
        "recomendacionesCompra": len(compra),
        "recomendacionesPublicacion": len(publicacion),
        "recomendacionesRevision": len(revision),
        "scorePromedioRecomendado": avg_score,
        "roiPromedioEstimado": avg_roi,
        "recomendacionesIgnorar": total - len(accionables),
    }


def destacados(recs: list[dict[str, Any]]) -> dict[str, Any]:
    """Las respuestas directas a las 5 preguntas de la vista."""
    accionables = [r for r in recs if r["recommendation_type"] != "Ignorar"]
    compra = [r for r in accionables if r["recommendation_type"] in TIPOS_COMPRA]
    publicacion = [r for r in accionables if r["recommendation_type"] in TIPOS_PUBLICACION]

    def _mejor(pool: list[dict[str, Any]], clave) -> dict[str, Any] | None:
        return max(pool, key=clave) if pool else None

    return {
        "comprarHoy": _mejor(compra or accionables, lambda r: (r["pricehunter_score"], r["estimated_margin"])),
        "publicarPrimero": _mejor(publicacion or accionables, lambda r: (r["viralidad"], r["pricehunter_score"])),
        "mejorRoi": _mejor(compra or accionables, lambda r: r["estimated_margin"]),
        "masViral": _mejor(accionables, lambda r: r["viralidad"]),
        "ignorar": len(recs) - len(accionables),
    }
