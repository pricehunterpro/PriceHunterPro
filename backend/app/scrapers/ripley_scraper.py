from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation

import httpx
from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper, ScrapedProduct, ScraperError, now_utc
from app.scrapers.stealth import random_user_agent

_BASE = "https://simple.ripley.com.pe"
_MAX_PAGES = 3

# Category slugs with their display names
_CATEGORY_SLUGS = [
    ("/tecnologia", "Tecnología"),
    ("/electrodomesticos-y-muebles", "Electrodomésticos"),
    ("/audio-y-video", "Audio y Video"),
    ("/celulares-y-tablets", "Celulares"),
    ("/computacion", "Computación"),
    ("/deportes", "Deportes"),
    ("/ropa-y-calzado-hombre", "Ropa Hombre"),
    ("/ropa-y-calzado-mujer", "Ropa Mujer"),
    ("/jugueteria", "Juguetería"),
    ("/bebes-y-ninos", "Bebés y Niños"),
    ("/belleza-y-cuidado-personal", "Belleza"),
    ("/relojes-y-joyas", "Relojes y Joyas"),
    ("/gaming", "Gaming"),
]


def _make_client() -> httpx.AsyncClient:
    # Only User-Agent — extra headers trigger a CDN path that strips __NEXT_DATA__ results
    return httpx.AsyncClient(
        headers={"User-Agent": random_user_agent()},
        follow_redirects=True,
        timeout=30,
    )


async def _get_next_data(client: httpx.AsyncClient, url: str) -> dict:
    try:
        r = await client.get(url)
        if r.status_code not in (200, 404):  # Ripley returns 404 for some valid pages
            return {}
        # Decode explicitly as UTF-8 to avoid BeautifulSoup Latin-1 misdetection
        html = r.content.decode("utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        tag = soup.find("script", id="__NEXT_DATA__")
        return json.loads(tag.string) if tag else {}
    except Exception:
        return {}


def _parse_ripley_price(raw: str | int | float) -> Decimal:
    """Parse 'S/ 3,699.00' or 3699 to Decimal."""
    if isinstance(raw, (int, float)):
        return Decimal(str(raw))
    text = str(raw).replace(",", "")
    digits = re.sub(r"[^\d.]", "", text)
    try:
        return Decimal(digits) if digits else Decimal("0")
    except InvalidOperation:
        return Decimal("0")


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

        # Build URL from slugified_url or SKU
        url = item.get("slugified_url") or ""
        if url and not url.startswith("http"):
            url = _BASE + url
        elif sku:
            url = f"{_BASE}/{sku}"

        # in_stock: badge must indicate a concrete delivery/pickup commitment.
        # "despacho" excluded — also used for shipping-policy banners on out-of-stock items.
        _DELIVERY = ("llega", "retira", "recíbelo", "recibelo", "disponible")
        all_badges = (
            (item.get("badgesTop") or [])
            + (item.get("badgesMiddle") or [])
            + (item.get("badgesBottom") or [])
        )
        badge_labels = [b.get("label", "").lower() for b in all_badges]
        in_stock = any(kw in lbl for kw in _DELIVERY for lbl in badge_labels)

        out.append(ScrapedProduct(
            name=name,
            brand=str(item.get("brand") or ""),
            store="ripley",
            store_sku=sku,
            url=url,
            current_price=current_price,
            original_price=original_price,
            discount_percentage=discount,
            in_stock=in_stock,
            image_url=str(image_url),
            category=category,
            scraped_at=now_utc(),
        ))
    return out


def _extract_from_page_data(data: dict, category: str) -> list[ScrapedProduct]:
    """Extract products from Ripley __NEXT_DATA__ structure."""
    page_props = (data.get("props") or {}).get("pageProps") or {}

    # Primary source: findabilityProps.data.products
    products = (page_props.get("findabilityProps") or {}).get("data", {}).get("products") or []
    if products:
        return _products_from_findability(products, category)

    # Fallback: catalog.products
    products = (page_props.get("catalog") or {}).get("products") or []
    if products:
        return _products_from_findability(products, category)

    return []


class RipleyScraper(BaseScraper):
    store = "ripley"

    async def get_category(self, category_url: str = "") -> list[ScrapedProduct]:
        all_products: list[ScrapedProduct] = []
        try:
            async with _make_client() as client:
                for slug, cat_name in _CATEGORY_SLUGS:
                    for page_num in range(1, _MAX_PAGES + 1):
                        url = f"{_BASE}{slug}?page={page_num}&sort=-discount"
                        data = await _get_next_data(client, url)
                        items = _extract_from_page_data(data, cat_name)
                        if not items:
                            break
                        all_products.extend(items)
                        if len(items) < 20:
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
