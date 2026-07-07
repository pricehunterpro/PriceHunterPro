from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation

import httpx
from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper, ScrapedProduct, ScraperError, now_utc
from app.scrapers.stealth import random_user_agent

_BASE      = "https://www.sodimac.com.pe/sodimac-pe"
_MAX_PAGES = 8

# /lista/{CATID}/{Name} — categorías con mayor potencial de deals
_CATEGORY_SLUGS = [
    # Electrohogar — categoría madre (más páginas para no perder deals)
    "/lista/cat40584/Electrohogar",
    # Lavado — subcategoría específica donde vive la LRI-312C
    "/lista/cat780522/Lavadoras",
    "/lista/cat7180470/Lavadora-Secadora",
    "/lista/CATG19032/Refrigeracion",
    "/lista/CATG19033/Linea-blanca",
    # Tecnología
    "/lista/cat40793/Tecnologia",
    # Herramientas y maquinaria
    "/lista/CATG46232/Herramientas-y-maquinaria",
    # Construcción y ferretería
    "/lista/CATG11946/Construccion-y-ferreteria",
    # Cocina y baño
    "/lista/CATG11945/Cocina-y-bano",
    # Jardín y terraza
    "/lista/CATG11948/Jardin-y-terraza",
    # Deportes y aire libre
    "/lista/cat40571/Deportes-y-aire-libre",
    # Automotriz
    "/lista/CATG11944/Automotriz",
    # Muebles y organización
    "/lista/CATG11951/Muebles-y-Organizacion",
]


def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": random_user_agent()},
        follow_redirects=True,
        timeout=30,
    )


async def _get_next_data(client: httpx.AsyncClient, url: str) -> dict:
    try:
        r = await client.get(url)
        if r.status_code != 200:
            return {}
        html = r.content.decode("utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        tag = soup.find("script", id="__NEXT_DATA__")
        return json.loads(tag.string) if tag else {}
    except Exception:
        return {}


def _parse_price(raw: str | list) -> Decimal:
    if isinstance(raw, list):
        raw = "".join(str(x) for x in raw)
    text = str(raw).replace(",", "")
    digits = re.sub(r"[^\d.]", "", text)
    try:
        return Decimal(digits) if digits else Decimal("0")
    except InvalidOperation:
        return Decimal("0")


def _products_from_results(results: list, category: str) -> list[ScrapedProduct]:
    out: list[ScrapedProduct] = []
    for item in results:
        name = item.get("displayName") or ""
        if not name:
            continue

        prices = item.get("prices") or []
        current_price  = Decimal("0")
        original_price = Decimal("0")

        for p in prices:
            val   = _parse_price(p.get("price", []))
            ptype = p.get("type", "")
            crossed = p.get("crossed", False)

            # Precio de venta: preferir internetPrice > eventPrice > cmrPrice
            if ptype == "internetPrice" and current_price == Decimal("0"):
                current_price = val
            elif ptype == "eventPrice" and current_price == Decimal("0"):
                current_price = val
            elif ptype == "cmrPrice" and current_price == Decimal("0"):
                current_price = val

            # Precio original: normalPrice tachado
            if crossed and ptype == "normalPrice" and original_price == Decimal("0"):
                original_price = val

        if current_price == Decimal("0"):
            continue
        if original_price < current_price:
            original_price = current_price

        # Descuento: preferir badge, si no calcular
        discount = Decimal("0")
        badge_label = (item.get("discountBadge") or {}).get("label", "")
        pct_str = re.sub(r"[^\d]", "", badge_label)
        if pct_str:
            discount = Decimal(pct_str)
        elif original_price > Decimal("0"):
            discount = ((original_price - current_price) / original_price * 100).quantize(Decimal("0.01"))

        media = item.get("mediaUrls") or []
        image_url = media[0] if media else ""

        stickers = item.get("meatStickers") or []
        in_stock = len(stickers) > 0 or bool(badge_label) or (original_price > current_price)

        url = str(item.get("url") or "")
        if url and not url.startswith("http"):
            url = f"https://www.sodimac.com.pe{url}"

        out.append(ScrapedProduct(
            name=name,
            brand=str(item.get("brand") or ""),
            store="sodimac",
            store_sku=str(item.get("skuId") or item.get("productId") or ""),
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


class SodimacScraper(BaseScraper):
    store = "sodimac"

    async def get_category(self, category_url: str = "") -> list[ScrapedProduct]:
        all_products: list[ScrapedProduct] = []
        try:
            async with _make_client() as client:
                for slug in _CATEGORY_SLUGS:
                    raw = slug.split("/")[-1]
                    cat_name = raw.replace("-y-", " y ").replace("-", " ").title()
                    for page_num in range(1, _MAX_PAGES + 1):
                        url = f"{_BASE}{slug}?currentPage={page_num}"
                        data = await _get_next_data(client, url)
                        results = (data.get("props") or {}).get("pageProps", {}).get("results") or []
                        if not results:
                            break
                        items = _products_from_results(results, cat_name)
                        all_products.extend(items)
                        if len(results) < 20:
                            break
        except Exception as exc:
            raise ScraperError(f"Sodimac get_category error: {exc}") from exc
        return all_products

    async def search_products(self, query: str) -> list[ScrapedProduct]:
        try:
            async with _make_client() as client:
                url = f"{_BASE}/buscar/?Ntt={query}&currentPage=1"
                data = await _get_next_data(client, url)
                results = (data.get("props") or {}).get("pageProps", {}).get("results") or []
                return _products_from_results(results, "Búsqueda")
        except Exception as exc:
            raise ScraperError(f"Sodimac search error: {exc}") from exc

    async def get_product_detail(self, url: str) -> ScrapedProduct:
        raise NotImplementedError
