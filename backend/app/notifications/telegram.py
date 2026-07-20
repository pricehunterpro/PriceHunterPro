from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

STORE_EMOJI: dict[str, str] = {
    "falabella": "🟢",
    "ripley":    "🟣",
    "plazavea":  "🔴",
    "oechsle":   "🟡",
    "promart":   "🟠",
    "tottus":    "🔵",
    "hiraoka":   "🟩",
    "shopstar":  "🟦",
}

HASHTAGS = "#OfertasPeru #PriceHunterPro #DescuentosPeru #GangasPeru"


def _build_caption(deal: dict[str, Any]) -> str:
    store_icon = STORE_EMOJI.get(deal.get("store", ""), "🏪")
    store_name = deal.get("store", "").capitalize()
    name = deal.get("name", "")
    original = deal.get("originalPrice", 0)
    current = deal.get("currentPrice", 0)
    discount = deal.get("discountPct", 0)
    margin = deal.get("marginPct", 0)
    savings = round(original - current, 2)
    url = deal.get("url", "")

    return (
        f"🔥 *OFERTÓN PRICEHUNTER PRO*\n\n"
        f"📦 *{name}*\n\n"
        f"💰 Antes: ~~S/ {original:.2f}~~\n"
        f"✅ *Ahora: S/ {current:.2f}*\n"
        f"📉 Descuento: *{discount:.0f}%*\n"
        f"{store_icon} Tienda: *{store_name}*\n\n"
        f"🔗 [Ver oferta]({url})\n\n"
        f"⏳ _Precio sujeto a stock o cambios._\n\n"
        f"{HASHTAGS}"
    )


def _telegram_api_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def send_deal(deal: dict[str, Any], channel_id: str | None = None) -> bool:
    settings = get_settings()
    token = settings.telegram_bot_token
    target = channel_id or settings.telegram_channel

    if not token or not target:
        logger.warning("Telegram no configurado — token o canal vacío")
        return False

    caption = _build_caption(deal)
    image_url = deal.get("imageUrl") or deal.get("image_url")

    try:
        with httpx.Client(timeout=15) as client:
            if image_url:
                resp = client.post(
                    _telegram_api_url(token, "sendPhoto"),
                    json={
                        "chat_id": target,
                        "photo": image_url,
                        "caption": caption,
                        "parse_mode": "Markdown",
                    },
                )
            else:
                resp = client.post(
                    _telegram_api_url(token, "sendMessage"),
                    json={
                        "chat_id": target,
                        "text": caption,
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": False,
                    },
                )

        if resp.status_code == 200:
            logger.info("Deal publicado en Telegram canal %s: %s", target, deal.get("name"))
            return True

        logger.error("Error Telegram %s: %s", resp.status_code, resp.text)
        return False

    except httpx.RequestError as exc:
        logger.error("Error de red al publicar en Telegram: %s", exc)
        return False


def send_deals_batch(deals: list[dict[str, Any]], channel_id: str | None = None) -> int:
    """Publica una lista de deals. Retorna cuántos se enviaron con éxito."""
    sent = 0
    for deal in deals:
        if send_deal(deal, channel_id=channel_id):
            sent += 1
    return sent


def notify_admin(message: str) -> bool:
    """Envía un mensaje de texto al admin (no al canal)."""
    settings = get_settings()
    token = settings.telegram_bot_token
    admin_id = settings.telegram_admin_id

    if not token or not admin_id:
        return False

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                _telegram_api_url(token, "sendMessage"),
                json={"chat_id": admin_id, "text": message},
            )
        return resp.status_code == 200
    except httpx.RequestError:
        return False
