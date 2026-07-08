from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation

import httpx

from app.scrapers.base import BaseScraper, ScrapedProduct, ScraperError, now_utc
from app.scrapers.stealth import random_user_agent

_BASE = "https://www.tottus.com.pe"
_API = f"{_BASE}/api/catalog_system/pub/products/search"
_PAGE_SIZE = 50
_MAX_PAGES = 4
_TOP_DEALS_PAGES = 6

# Categorías principales de Tottus PE (VTEX)
_CATEGORIES: list[tuple[str, str]] = [
    # Tecnología
    ("1/",    "Tecnología"),
    ("1/2/",  "Celulares"),
    ("1/3/",  "Laptops y PCs"),
    ("1/4/",  "Televisores"),
    ("1/5/",  "Audio"),
    # Electrohogar
    ("6/",    "Electrohogar"),
    ("6/7/",  "Refrigeradoras"),
    ("6/8/",  "Lavadoras"),
    ("6/9/",  "Cocinas"),
    ("6/10/", "Electrodomésticos"),
    # Moda
    ("12/",   "Moda Mujer"),
    ("13/",   "Moda Hombre"),
    # Deportes
    ("14/",   "Deportes"),
    # Hogar
    ("15/",   "Hogar"),
]


def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={
            "User-Agent": random_user_agent(),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "es-PE,es;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": f"{_BASE}/",
            "Origin": _BASE,
            "DNT": "1",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        },
        follow_redirects=True,
        timeout=30,
    )


def _parse_price(val) -> Decimal:
    try:
        return Decimal(str(val)) if val else Decimal("0")
    except InvalidOperation:
        return Decimal("0")


def _extract_category(vtex_categories: list[str], fallback: str) -> str:
    if not vtex_categories:
        return fallback
    path = vtex_categories[0]
    parts = [p.strip() for p in path.split("/") if p.strip()]
    if len(parts) >= 2:
        return parts[1]
    if parts:
        return parts[0]
    return fallback


def _products_from_vtex(data: list, fallback_category: str) -> list[ScrapedProduct]:
    out: list[ScrapedProduct] = []
    for p in data:
        name = p.get("productName") or ""
        if not name:
            continue

        items = p.get("items") or []
        if not items:
            continue

        item = items[0]
        sellers = item.get("sellers") or []
        if not sellers:
            continue

        co = sellers[0].get("commertialOffer") or {}
        current_price = _parse_price(co.get("Price"))
        original_price = _parse_price(co.get("ListPrice") or co.get("Price"))
        available = int(co.get("AvailableQuantity") or 0)
        is_available = bool(co.get("IsAvailable", True))

        if current_price == Decimal("0"):
            continue
        if original_price < current_price:
            original_price = current_price

        discount = Decimal("0")
        if original_price > current_price:
            discount = ((original_price - current_price) / original_price * 100).quantize(Decimal("0.01"))

        images = item.get("images") or []
        image_url = images[0].get("imageUrl", "") if images else ""

        link_text = p.get("linkText") or ""
        url = f"{_BASE}/{link_text}/p" if link_text else ""

        category = _extract_category(p.get("categories") or [], fallback_category)

        out.append(ScrapedProduct(
            name=name,
            brand=str(p.get("brand") or ""),
            store="tottus",
            store_sku=str(p.get("productId") or ""),
            url=url,
            current_price=current_price,
            original_price=original_price,
            discount_percentage=discount,
            in_stock=available > 0 and is_available,
            image_url=image_url,
            category=category,
            scraped_at=now_utc(),
        ))
    return out


class TottusScraper(BaseScraper):
    store = "tottus"

    async def _scrape_top_deals(self, client: httpx.AsyncClient) -> list[ScrapedProduct]:
        results: list[ScrapedProduct] = []
        for page in range(_TOP_DEALS_PAGES):
            start = page * _PAGE_SIZE
            end = start + _PAGE_SIZE - 1
            params = {"_from": start, "_to": end, "O": "OrderByBestDiscountDESC"}
            try:
                r = await client.get(_API, params=params)
                if r.status_code == 403:
                    break
                if r.status_code not in (200, 206):
                    break
                data = r.json()
                if not data:
                    break
                results.extend(_products_from_vtex(data, "Oferta"))
                await asyncio.sleep(1.0)
                if len(data) < _PAGE_SIZE:
                    break
            except Exception:
                break
        return results

    async def get_category(self, category_url: str = "") -> list[ScrapedProduct]:
        all_products: list[ScrapedProduct] = []
        try:
            async with _make_client() as client:
                # 1. Top deals generales (descuentos más altos sin filtro de categoría)
                top_deals = await self._scrape_top_deals(client)
                all_products.extend(top_deals)

                # 2. Solo continúa con categorías si la API respondió correctamente
                if not top_deals:
                    return all_products

                seen_skus = {p.store_sku for p in all_products}
                for cat_id, cat_name in _CATEGORIES:
                    for page in range(_MAX_PAGES):
                        start = page * _PAGE_SIZE
                        end = start + _PAGE_SIZE - 1
                        params = {
                            "fq": f"C:/{cat_id}",
                            "_from": start,
                            "_to": end,
                            "O": "OrderByBestDiscountDESC",
                        }
                        try:
                            r = await client.get(_API, params=params)
                            if r.status_code == 403:
                                break
                            if r.status_code not in (200, 206):
                                break
                            data = r.json()
                            if not data:
                                break
                            items = _products_from_vtex(data, cat_name)
                            new_items = [i for i in items if i.store_sku not in seen_skus]
                            seen_skus.update(i.store_sku for i in new_items)
                            all_products.extend(new_items)
                            await asyncio.sleep(1.0)
                            if len(data) < _PAGE_SIZE:
                                break
                        except Exception:
                            break
        except Exception as exc:
            raise ScraperError(f"Tottus get_category error: {exc}") from exc
        return all_products

    async def search_products(self, query: str) -> list[ScrapedProduct]:
        try:
            async with _make_client() as client:
                params = {"ft": query, "_from": 0, "_to": 19}
                r = await client.get(_API, params=params)
                if r.status_code not in (200, 206):
                    return []
                return _products_from_vtex(r.json(), "Búsqueda")
        except Exception as exc:
            raise ScraperError(f"Tottus search error: {exc}") from exc

    async def get_product_detail(self, url: str) -> ScrapedProduct:
        raise NotImplementedError
