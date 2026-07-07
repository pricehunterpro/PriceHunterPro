from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation

import httpx

from app.scrapers.base import BaseScraper, ScrapedProduct, ScraperError, now_utc
from app.scrapers.stealth import random_user_agent

_BASE     = "https://www.estilos.com.pe"
_API      = f"{_BASE}/api/catalog_system/pub/products/search"
_PAGE_SIZE = 50
_MAX_PAGES = 4
_TOP_DEALS_PAGES = 6  # 300 productos con mayor descuento

_CATEGORIES: list[tuple[str, str]] = [
    # Tecnología
    ("100000000/101000000/", "Telefonía"),
    ("100000000/102000000/", "Computadoras"),
    ("100000000/103000000/", "Televisores"),
    ("100000000/104000000/", "Audio"),
    ("100000000/106000000/", "Gaming"),
    # Electrohogar
    ("200000000/201000000/", "Electrodomésticos"),
    ("200000000/202000000/", "Línea Blanca"),
    ("200000000/203000000/", "Climatización"),
    # Moda
    ("500000000/501000000/", "Moda Mujer"),
    ("500000000/502000000/", "Moda Hombre"),
    # Calzado
    ("600000000/601000000/", "Zapatillas"),
    ("600000000/602000000/", "Zapatos"),
    # Deportes
    ("900000000/901000000/", "Ropa Deportiva"),
    ("900000000/902000000/", "Fitness"),
    ("900000000/907000000/", "Ciclismo"),
    # Dormitorio
    ("400000000/401000000/", "Ropa de Cama"),
    ("400000000/406000000/", "Camas"),
    # Cocina y Baño
    ("1400000000/1403000000/", "Cocina"),
    # Juguetería
    ("700000000/701000000/", "Juguetería"),
]


def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": random_user_agent()},
        follow_redirects=True,
        timeout=30,
    )


def _parse_price(val) -> Decimal:
    try:
        return Decimal(str(val)) if val else Decimal("0")
    except InvalidOperation:
        return Decimal("0")


def _extract_category(categories: list[str], fallback: str) -> str:
    if not categories:
        return fallback
    parts = [p.strip() for p in categories[0].split("/") if p.strip()]
    return parts[-1].title() if parts else fallback


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
        current_price  = _parse_price(co.get("Price"))
        original_price = _parse_price(co.get("ListPrice") or co.get("Price"))
        available  = int(co.get("AvailableQuantity") or 0)
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
            store="estilos",
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


class EstilosScraper(BaseScraper):
    store = "estilos"

    async def _scrape_top_deals(self, client: httpx.AsyncClient) -> list[ScrapedProduct]:
        results: list[ScrapedProduct] = []
        for page in range(_TOP_DEALS_PAGES):
            start = page * _PAGE_SIZE
            params = {"_from": start, "_to": start + _PAGE_SIZE - 1,
                      "O": "OrderByBestDiscountDESC"}
            r = await client.get(_API, params=params)
            if r.status_code not in (200, 206):
                break
            data = r.json()
            if not data:
                break
            results.extend(_products_from_vtex(data, "Oferta"))
            await asyncio.sleep(0.5)
            if len(data) < _PAGE_SIZE:
                break
        return results

    async def get_category(self, category_url: str = "") -> list[ScrapedProduct]:
        all_products: list[ScrapedProduct] = []
        try:
            async with _make_client() as client:
                # 1. Top deals generales
                top_deals = await self._scrape_top_deals(client)
                all_products.extend(top_deals)

                # 2. Categorías específicas
                seen_skus = {p.store_sku for p in all_products}
                for cat_path, cat_name in _CATEGORIES:
                    for page in range(_MAX_PAGES):
                        start = page * _PAGE_SIZE
                        params = {"fq": f"C:/{cat_path}", "_from": start,
                                  "_to": start + _PAGE_SIZE - 1,
                                  "O": "OrderByBestDiscountDESC"}
                        r = await client.get(_API, params=params)
                        if r.status_code not in (200, 206):
                            break
                        data = r.json()
                        if not data:
                            break
                        items = _products_from_vtex(data, cat_name)
                        new_items = [i for i in items if i.store_sku not in seen_skus]
                        seen_skus.update(i.store_sku for i in new_items)
                        all_products.extend(new_items)
                        await asyncio.sleep(0.5)
                        if len(data) < _PAGE_SIZE:
                            break
        except Exception as exc:
            raise ScraperError(f"Estilos get_category error: {exc}") from exc
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
            raise ScraperError(f"Estilos search error: {exc}") from exc

    async def get_product_detail(self, url: str) -> ScrapedProduct:
        raise NotImplementedError
