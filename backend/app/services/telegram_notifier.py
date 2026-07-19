from __future__ import annotations

import urllib.parse
import urllib.request

from app.core.config import get_settings


def _post(token: str, chat_id: str, message: str, image_url: str = "") -> bool:
    try:
        if image_url:
            endpoint = f"https://api.telegram.org/bot{token}/sendPhoto"
            payload = {
                "chat_id": chat_id,
                "photo": image_url,
                "caption": message,
                "parse_mode": "HTML",
            }
        else:
            endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
            }
        data = urllib.parse.urlencode(payload).encode("utf-8")
        urllib.request.urlopen(endpoint, data=data, timeout=10)
        return True
    except Exception:
        # Si sendPhoto falla (imagen inválida), reintenta solo con texto
        if image_url:
            return _post(token, chat_id, message)
        return False


def notify_new_alerts(new_alerts: list[dict], channel_id: str = "") -> bool:
    if not new_alerts:
        return False
    settings = get_settings()
    token = settings.telegram_bot_token
    admin_id = settings.telegram_admin_id
    if not channel_id:
        channel_id = settings.telegram_channel
    if not token or not channel_id:
        return False

    sent = False
    for alert in new_alerts[:10]:  # max 10 mensajes por raspado
        name = alert.get("name", "")[:50]
        store = alert.get("store", "").upper()
        price = alert.get("currentPrice", 0)
        avg = alert.get("avgMarketPrice", 0)
        diff = alert.get("mktDiffPct", 0)
        url = alert.get("url", "")
        image_url = alert.get("imageUrl", "")
        header = (
            "🚨 ERROR DE PRECIO — PriceHunter Pro"
            if alert.get("priceError")
            else "🔥 Alerta PriceHunter Pro"
        )
        msg = (
            f"<b>{header}</b>\n"
            f"📦 {name}\n"
            f"🏪 {store}\n"
            f"💰 S/ {price:.2f} <s>S/ {avg:.2f}</s>\n"
            f"📉 {diff}% bajo su precio histórico\n"
            f"🔗 <a href=\"{url}\">Ver oferta</a>"
        )
        ok = _post(token, channel_id, msg, image_url)
        if admin_id:
            _post(token, admin_id, msg, image_url)
        if ok:
            sent = True
    return sent
