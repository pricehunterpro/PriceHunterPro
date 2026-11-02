from __future__ import annotations

import html
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


def esc(texto: Any) -> str:
    """Escapa para parse_mode=HTML. Con el Markdown de antes, un `_`, `*` o `[` en
    el nombre de un producto hacía que Telegram rechazara el mensaje entero."""
    return html.escape(str(texto or ""), quote=True)


def recortar(nombre: Any, largo: int = 52) -> str:
    """Recorta el nombre sin partir una palabra a la mitad (las fichas técnicas de
    las tiendas son larguísimas y el gancho es el precio, no el modelo completo)."""
    nombre = " ".join(str(nombre or "").split())
    if len(nombre) <= largo:
        return nombre
    corte = nombre[:largo]
    if nombre[largo] != " " and " " in corte:
        corte = corte.rsplit(" ", 1)[0]
    return corte.rstrip(" ,;:-/(") + "…"


def enlace_canal(canal: str | None = None) -> str:
    """Enlace público para unirse al canal, o '' si no se puede armar.

    Primero el ajuste manual (Configuración > Publicaciones); si no hay, se
    deduce del canal cuando es un @usuario. Un ID numérico (-100…) no tiene
    enlace público derivable."""
    try:
        from app.services.settings_service import get_setting
        manual = str(get_setting("publicaciones", "enlace_canal", "") or "").strip()
    except Exception:
        manual = ""
    if manual:
        return manual
    canal = (canal or "").strip()
    if canal.startswith("@") and len(canal) > 1:
        return f"https://t.me/{canal[1:]}"
    return ""


def pie_invitacion(canal: str | None = None) -> str:
    """Línea final que convierte a quien recibe un reenvío en miembro del canal."""
    enlace = enlace_canal(canal)
    if not enlace:
        return ""
    return f'📲 <a href="{esc(enlace)}">Únete al canal</a> y no te pierdas la próxima oferta'


def _build_caption(deal: dict[str, Any], canal: str | None = None) -> str:
    store_icon = STORE_EMOJI.get(deal.get("store", ""), "🏪")
    store_name = esc(str(deal.get("store", "")).capitalize())
    corto = esc(recortar(deal.get("name", "")))
    original = float(deal.get("originalPrice") or 0)
    current = float(deal.get("currentPrice") or 0)
    discount = float(deal.get("discountPct") or 0)
    url = str(deal.get("url") or "")

    # Titular estilo SUPERCUPON: PRODUCTO + PRECIO FINAL (lo que engancha), y el
    # antes/descuento de refuerzo.
    if current <= 5:
        gancho = f"🚨 <b>{corto} ¡a solo S/ {current:.2f}!</b>"
    elif current < 1000:
        gancho = f"🔥 <b>{corto} a solo S/ {current:.0f}</b>"
    else:
        gancho = f"🔥 <b>{corto} a S/ {current:,.0f}</b>"

    # Descuento REAL: si el precio está bajo su propio historial, la referencia es
    # el precio habitual (defendible) y no el "antes" que declara la tienda.
    habitual = float(deal.get("histMedian") or 0)
    if deal.get("verificada") and habitual > current > 0:
        real = round((1 - current / habitual) * 100)
        precios = (
            f"💰 Precio habitual <s>S/ {habitual:,.2f}</s> → <b>S/ {current:,.2f}</b>\n"
            f"✅ <b>Precio verificado:</b> {real}% más barato de lo normal"
        )
        ahorro = habitual - current
    else:
        precios = f"💰 Antes <s>S/ {original:,.2f}</s> → <b>S/ {current:,.2f}</b>  ·  <b>-{discount:.0f}%</b>"
        ahorro = original - current

    lineas = [gancho, "", precios]
    if ahorro >= 1:
        lineas.append(f"💸 Ahorras <b>S/ {ahorro:,.0f}</b>")
    lineas.append(f"{store_icon} {store_name}")
    if url:
        lineas += ["", f'🛒 <a href="{esc(url)}">Ver oferta</a>']
    lineas += ["", "<i>⏳ Stock limitado: el precio puede cambiar sin aviso.</i>"]
    pie = pie_invitacion(canal)
    if pie:
        lineas += ["", pie]
    lineas += ["", HASHTAGS]
    return "\n".join(lineas)


def _telegram_api_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def _normalizar_imagen(url: str) -> str:
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http://"):
        return "https://" + url[len("http://"):]
    return url


def _descargar_imagen(client: httpx.Client, url: str) -> bytes | None:
    try:
        r = client.get(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "image/jpeg,image/png,image/*;q=0.8"},
            follow_redirects=True,
        )
        tipo = r.headers.get("content-type", "")
        # Telegram exige <10 MB y JPG/PNG; WEBP/AVIF no los acepta como foto.
        if r.status_code == 200 and tipo.startswith("image/") and "webp" not in tipo \
                and "avif" not in tipo and 0 < len(r.content) < 9_000_000:
            return r.content
        logger.warning("Imagen no utilizable (%s, %s): %s", r.status_code, tipo, url)
    except httpx.RequestError as exc:
        logger.warning("No se pudo descargar la imagen %s: %s", url, exc)
    return None


def send_deal(deal: dict[str, Any], channel_id: str | None = None) -> bool:
    settings = get_settings()
    token = settings.telegram_bot_token
    target = channel_id or settings.telegram_channel

    if not token or not target:
        logger.warning("Telegram no configurado — token o canal vacío")
        return False

    caption = _build_caption(deal, target)
    image_url = deal.get("imageUrl") or deal.get("image_url")

    try:
        with httpx.Client(timeout=15) as client:
            resp = None
            if image_url:
                image_url = _normalizar_imagen(image_url)
                resp = client.post(
                    _telegram_api_url(token, "sendPhoto"),
                    json={
                        "chat_id": target,
                        "photo": image_url,
                        "caption": caption,
                        "parse_mode": "HTML",
                    },
                )
                if resp.status_code == 400:
                    # Telegram no pudo bajarla desde su lado (CDN con hotlink/UA):
                    # la bajamos nosotros y la subimos como archivo.
                    contenido = _descargar_imagen(client, image_url)
                    if contenido:
                        resp = client.post(
                            _telegram_api_url(token, "sendPhoto"),
                            data={"chat_id": target, "caption": caption, "parse_mode": "HTML"},
                            files={"photo": ("oferta.jpg", contenido)},
                        )
                if resp.status_code == 400:
                    # Imagen que Telegram no puede descargar (muy común con CDNs de
                    # tienda): antes la oferta se perdía. Sale igual, sin foto.
                    logger.warning("sendPhoto rechazado (%s); reintento sin imagen", resp.text)
                    resp = None
            if resp is None:
                resp = client.post(
                    _telegram_api_url(token, "sendMessage"),
                    json={
                        "chat_id": target,
                        "text": caption,
                        "parse_mode": "HTML",
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
