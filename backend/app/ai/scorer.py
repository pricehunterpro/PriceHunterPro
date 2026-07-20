from __future__ import annotations

from typing import Any


# Categorías de alta rotación para el score
_HIGH_ROTATION = {
    "celulares", "electrónica", "electronica", "computación", "computacion",
    "tecnología", "tecnologia", "audio", "gaming", "fotografía", "fotografia",
    "tablets", "videojuegos",
}
_MID_ROTATION = {
    "electrodomésticos", "electrodomesticos", "hogar", "deportes",
    "herramientas", "jardinería", "jardineria", "cocina",
}
_TOP_STORES  = {"falabella", "ripley", "plazavea", "tottus"}
_MID_STORES  = {"oechsle", "promart", "hiraoka", "shopstar"}


def calculate_score(deal: dict[str, Any]) -> dict[str, Any]:
    """
    Calcula el PriceHunter Score (0-100) para una oportunidad.
    Devuelve un dict con score, clasificacion, recomendacion y explicacion.
    """
    current     = float(deal.get("currentPrice",    0) or 0)
    discount    = float(deal.get("discountPct",      0) or 0)
    margin      = float(deal.get("marginPct",        0) or 0)
    avg_market  = float(deal.get("avgMarketPrice",   0) or 0)
    mkt_diff    = float(deal.get("mktDiffPct",       0) or 0)
    below_mkt   = bool(deal.get("belowMarket",   False))
    in_stock    = bool(deal.get("inStock",        True))
    store       = str(deal.get("store",             "")).lower()
    category    = str(deal.get("category",          "")).lower()

    score   = 0
    reasons: list[str] = []

    # ── 1. Precio vs histórico (0-30 pts) ─────────────────────
    if avg_market > 0 and below_mkt:
        if mkt_diff >= 30:
            score += 30
            reasons.append(f"{mkt_diff:.0f}% bajo precio histórico")
        elif mkt_diff >= 20:
            score += 22
            reasons.append(f"{mkt_diff:.0f}% bajo precio histórico")
        elif mkt_diff >= 10:
            score += 15
            reasons.append(f"{mkt_diff:.0f}% bajo precio histórico")
        else:
            score += 5

    # ── 2. Descuento (0-25 pts) ───────────────────────────────
    if discount >= 60:
        score += 25
        reasons.append(f"{discount:.0f}% descuento")
    elif discount >= 40:
        score += 18
        reasons.append(f"{discount:.0f}% descuento")
    elif discount >= 30:
        score += 12
        reasons.append(f"{discount:.0f}% descuento")
    elif discount >= 20:
        score += 8
    else:
        score += 3

    # ── 3. Margen estimado (0-20 pts) ─────────────────────────
    if margin >= 50:
        score += 20
        reasons.append(f"Margen {margin:.0f}%")
    elif margin >= 30:
        score += 14
        reasons.append(f"Margen {margin:.0f}%")
    elif margin >= 15:
        score += 8
    else:
        score += 2

    # ── 4. Stock disponible (0-10 pts) ────────────────────────
    if in_stock:
        score += 10
        reasons.append("En stock")

    # ── 5. Categoría (0-8 pts) ────────────────────────────────
    if any(h in category for h in _HIGH_ROTATION):
        score += 8
        reasons.append("Categoría alta rotación")
    elif any(m in category for m in _MID_ROTATION):
        score += 5
    else:
        score += 2

    # ── 6. Tienda confiable (0-5 pts) ─────────────────────────
    if store in _TOP_STORES:
        score += 5
        reasons.append(f"Tienda verificada")
    elif store in _MID_STORES:
        score += 3
    else:
        score += 1

    # ── 7. Precio sospechoso (penalización) ───────────────────
    if avg_market > 0 and current < avg_market * 0.35:
        score -= 20
        reasons.append("⚠ Precio muy inusual vs histórico")

    score = max(0, min(100, score))

    # ── Clasificación ─────────────────────────────────────────
    if score >= 95:
        clasificacion = "Ganga Extrema"
        clasificacion_emoji = "🔥 Ganga Extrema"
    elif score >= 80:
        clasificacion = "Excelente Oferta"
        clasificacion_emoji = "✅ Excelente Oferta"
    elif score >= 60:
        clasificacion = "Buena Oferta"
        clasificacion_emoji = "🟡 Buena Oferta"
    else:
        clasificacion = "Oferta Normal"
        clasificacion_emoji = "⚪ Oferta Normal"

    # ── Recomendación ─────────────────────────────────────────
    if score >= 80 and below_mkt:
        recomendacion = "Comprar + Publicar"
    elif score >= 80:
        recomendacion = "Comprar"
    elif score >= 65:
        recomendacion = "Comprar"
    elif score >= 45:
        recomendacion = "Revisar"
    else:
        recomendacion = "Ignorar"

    explicacion = " · ".join(reasons) if reasons else "Descuento moderado sin datos históricos"

    return {
        "score":               score,
        "clasificacion":       clasificacion,
        "clasificacionEmoji":  clasificacion_emoji,
        "recomendacion":       recomendacion,
        "explicacion":         explicacion,
    }
