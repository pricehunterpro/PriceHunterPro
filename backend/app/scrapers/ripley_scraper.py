from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation

import httpx
from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper, ScrapedProduct, ScraperError, now_utc
from app.scrapers.stealth import random_user_agent

_BASE = "https://simple.ripley.com.pe"
_MAX_PAGES = 6

# Slugs verificados (2026-07-08). Ripley usa categorías simples de un nivel;
# los slugs largos anteriores devolvían 404, por eso solo se raspaba tecnología.
_CATEGORY_SLUGS = [
    ("/tecnologia",          "Tecnología"),
    ("/celulares",           "Celulares"),
    ("/electrohogar",        "Electrohogar"),
    ("/hogar",               "Hogar"),
    ("/hogar/ropa-de-cama",  "Ropa de Cama"),
    ("/dormitorio",          "Dormitorio"),
    ("/muebles",             "Muebles"),
    ("/mujer",               "Moda Mujer"),
    ("/hombre",              "Moda Hombre"),
    ("/calzado",             "Calzado"),
    ("/deporte",             "Deportes"),
    ("/belleza",             "Belleza"),
    ("/infantil",            "Infantil"),
    ("/bebes",               "Bebés"),
    ("/mascotas",            "Mascotas"),
]

_OUT_OF_STOCK_KW = ("agotado", "sin stock", "no disponible", "out of stock")


def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={
            "User-Agent": random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "es-PE,es;q=0.9,en-US;q=0.8,en;q=0.7",
        },
        follow_redirects=True,
        timeout=30,
    )


async def _get_next_data(client: httpx.AsyncClient, url: str) -> dict:
    try:
        r = await client.get(url)
        if r.status_code not in (200, 404):
            return {}
        html = r.content.decode("utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        tag = soup.find("script", id="__NEXT_DATA__")
        return json.loads(tag.string) if tag else {}
    except Exception:
        return {}


def _parse_ripley_price(raw: str | int | float) -> Decimal:
    if isinstance(raw, (int, float)):
        return Decimal(str(raw))
    text = str(raw).replace(",", "")
    digits = re.sub(r"[^\d.]", "", text)
    try:
        return Decimal(digits) if digits else Decimal("0")
    except InvalidOperation:
        return Decimal("0")


def _is_in_stock(item: dict) -> bool:
    """True si el producto está disponible.

    Ripley usa badges para indicar disponibilidad de entrega/retiro.
    Si no hay badges, asumimos en stock (el producto está listado en el catálogo).
    Solo marcamos out-of-stock si hay texto explícito de agotado.
    """
    all_badges = (
        (item.get("badgesTop") or [])
        + (item.get("badgesMiddle") or [])
        + (item.get("badgesBottom") or [])
    )
    badge_labels = [b.get("label", "").lower() for b in all_badges]

    # Explícitamente agotado
    if any(kw in lbl for kw in _OUT_OF_STOCK_KW for lbl in badge_labels):
        return False

    # Badges de entrega/retiro presentes → en stock
    _DELIVERY = ("llega", "retira", "recíbelo", "recibelo", "disponible", "despacho", "pick")
    if badge_labels and any(kw in lbl for kw in _DELIVERY for lbl in badge_labels):
        return True

    # Sin badges → el producto aparece en listado, asumimos en stock
    return True


def _products_from_findability(products_list: list, category: str) -> list[ScrapedProduct]:
    out: list[ScrapedProduct] = []
    for item in products_list:
        name = item.get("name") or ""
        if not name:
            continue

        price_number = item.get("priceNumber") or 0
        current_price = Decimal(str(price_number)) if price_number else _parse_ripley_price(item.get("price", ""))
        original_price = _parse_ripley_price(item.get("oldPrice", "")) or current_price

        if current_price == Decimal("0"):
            continue
        if original_price < current_price:
            original_price = current_price

        discount_pct = item.get("discount") or 0
        discount = Decimal(str(discount_pct)) if discount_pct else (
            ((original_price - current_price) / original_price * 100).quantize(Decimal("0.01"))
            if original_price > Decimal("0") else Decimal("0")
        )

        sku = str(item.get("parentProductID") or item.get("sku") or "")
        images = item.get("images") or [item.get("primaryImage") or ""]
        image_url = images[0] if images else ""

        url = item.get("slugified_url") or ""
        if url and not url.startswith("http"):
            url = _BASE + url
        elif sku:
            url = f"{_BASE}/{sku}"

        out.append(ScrapedProduct(
            name=name,
            brand=str(item.get("brand") or ""),
            store="ripley",
            store_sku=sku,
            url=url,
            current_price=current_price,
            original_price=original_price,
            discount_percentage=discount,
            in_stock=_is_in_stock(item),
            image_url=str(image_url),
            category=category,
            scraped_at=now_utc(),
        ))
    return out


def _extract_from_page_data(data: dict, category: str) -> list[ScrapedProduct]:
    page_props = (data.get("props") or {}).get("pageProps") or {}

    products = (page_props.get("findabilityProps") or {}).get("data", {}).get("products") or []
    if products:
        return _products_from_findability(products, category)

    products = (page_props.get("catalog") or {}).get("products") or []
    if products:
        return _products_from_findability(products, category)

    return []


class RipleyScraper(BaseScraper):
    store = "ripley"

    async def get_category(self, category_url: str = "") -> list[ScrapedProduct]:
        all_products: list[ScrapedProduct] = []
        seen_skus: set[str] = set()
        try:
            async with _make_client() as client:
                for slug, cat_name in _CATEGORY_SLUGS:
                    for page_num in range(1, _MAX_PAGES + 1):
                        # Sin sort=-discount: obtenemos todos los productos del catálogo
                        url = f"{_BASE}{slug}?page={page_num}"
                        data = await _get_next_data(client, url)
                        items = _extract_from_page_data(data, cat_name)
                        if not items:
                            break
                        new_items = [i for i in items if i.store_sku not in seen_skus]
                        seen_skus.update(i.store_sku for i in new_items)
                        all_products.extend(new_items)
                        if len(items) < 10:
                            break
        except Exception as exc:
            raise ScraperError(f"Ripley get_category error: {exc}") from exc
        return all_products

    async def search_products(self, query: str) -> list[ScrapedProduct]:
        try:
            async with _make_client() as client:
                url = f"{_BASE}/search?query={query}"
                data = await _get_next_data(client, url)
                return _extract_from_page_data(data, "Búsqueda")
        except Exception as exc:
            raise ScraperError(f"Ripley search error: {exc}") from exc

    async def get_product_detail(self, url: str) -> ScrapedProduct:
        raise NotImplementedError
