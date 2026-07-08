from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation

import httpx

from app.scrapers.base import BaseScraper, ScrapedProduct, ScraperError, now_utc
from app.scrapers.stealth import random_user_agent

_BASE = "https://www.oechsle.pe"
_API = f"{_BASE}/api/catalog_system/pub/products/search"
_PAGE_SIZE = 50
_MAX_PAGES = 10  # hasta 500 productos por categoría (Lavado/TV/etc. tienen 500)
_TOP_DEALS_PAGES = 6  # 300 productos con mayor descuento sin filtro de categoría

# (fq_path, fallback_name) — paths con trailing slash obligatorio en Oechsle
_CATEGORIES: list[tuple[str, str]] = [
    # --- Tecnología (padre 160) ---
    ("160/171/",    "Televisores"),
    ("160/168/",    "Computo"),
    ("160/170/",    "Telefonía"),
    ("160/167/",    "Audio"),
    ("160/172/",    "Videojuegos"),
    ("160/1222396/","Cine en Casa"),
    ("160/1222982/","Audífonos"),
    # --- Electrohogar (padre 161) ---
    ("161/201/",    "Refrigeración"),
    ("161/332/",    "Lavado"),
    ("161/198/",    "Cocinas"),
    ("161/164/",    "Electrodomésticos"),
    ("161/260/",    "Climatización"),
    # --- Deportes (padre 9) ---
    ("9/16/",       "Bicicletas"),
    ("9/545/",      "Ropa Deportiva Hombre"),
    ("9/546/",      "Ropa Deportiva Mujer"),
    # --- Moda (padre 504) ---
    ("504/505/",    "Moda Mujer"),
    ("504/506/",    "Moda Hombre"),
    # --- Zapatillas (padre 1223006) ---
    ("1223006/1222299/", "Zapatillas Mujer"),
    ("1223006/1222300/", "Zapatillas Hombre"),
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


def _extract_category(vtex_categories: list[str], fallback: str) -> str:
    if not vtex_categories:
        return fallback
    parts = [p.strip() for p in vtex_categories[0].split("/") if p.strip()]
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
        # IsAvailable reflects "purchasable online" — more reliable than AvailableQuantity alone
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
            store="oechsle",
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


class OechsleScraper(BaseScraper):
    store = "oechsle"

    async def _scrape_top_deals(self, client: httpx.AsyncClient) -> list[ScrapedProduct]:
        """Raspa los mejores descuentos de Oechsle sin filtro de categoría."""
        results: list[ScrapedProduct] = []
        for page in range(_TOP_DEALS_PAGES):
            start = page * _PAGE_SIZE
            end = start + _PAGE_SIZE - 1
            params = {
                "_from": start,
                "_to": end,
                "O": "OrderByBestDiscountDESC",
            }
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
                # 1. Top deals generales (captura combos y ofertas fuera de categorías)
                top_deals = await self._scrape_top_deals(client)
                all_products.extend(top_deals)

                # 2. Categorías específicas
                seen_skus = {p.store_sku for p in all_products}
                for fq_path, cat_name in _CATEGORIES:
                    for page in range(_MAX_PAGES):
                        start = page * _PAGE_SIZE
                        end = start + _PAGE_SIZE - 1
                        params = {
                            "fq": f"C:/{fq_path}",
                            "_from": start,
                            "_to": end,
                            "O": "OrderByBestDiscountDESC",
                        }
                        r = await client.get(_API, params=params)
                        if r.status_code not in (200, 206):
                            break
                        data = r.json()
                        if not data:
                            break
                        items = _products_from_vtex(data, cat_name)
                        # Evitar duplicados con los top deals
                        new_items = [i for i in items if i.store_sku not in seen_skus]
                        seen_skus.update(i.store_sku for i in new_items)
                        all_products.extend(new_items)
                        await asyncio.sleep(0.5)
                        if len(data) < _PAGE_SIZE:
                            break
        except Exception as exc:
            raise ScraperError(f"Oechsle get_category error: {exc}") from exc
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
            raise ScraperError(f"Oechsle search error: {exc}") from exc

    async def get_product_detail(self, url: str) -> ScrapedProduct:
        raise NotImplementedError
