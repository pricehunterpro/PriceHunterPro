from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation

import httpx

from app.scrapers.base import BaseScraper, ScrapedProduct, ScraperError, now_utc
from app.scrapers.stealth import random_user_agent

_BASE = "https://www.plazavea.com.pe"
_API = f"{_BASE}/api/catalog_system/pub/products/search"
_PAGE_SIZE = 50
_MAX_PAGES = 4
_TOP_DEALS_PAGES = 6

# Estructura jerárquica: (fq_path, fallback_name)
# Subcategorías usan path completo padre/hijo: C:/678/687/
# Categorías de primer nivel usan ID simple: C:/3072/
_CATEGORIES: list[tuple[str, str]] = [
    # --- Tecnología (padre 678) ---
    ("678/687",  "Televisores"),      # TV LED, QLED, OLED, QNED
    ("678/683",  "Computo"),          # Laptops, PCs, Impresoras
    ("678/686",  "Telefonía"),        # Smartphones, Accesorios
    ("678/682",  "Audio"),            # Audífonos, Parlantes, Hi-Fi
    ("678/689",  "Videojuegos"),      # Consolas, Juegos, Accesorios Gamer
    ("678/1683", "Cine en Casa"),     # Proyectores, Soundbars
    # --- Electrohogar (padre 679) ---
    ("679/693",  "Refrigeración"),    # Refrigeradoras, Congeladoras
    ("679/691",  "Lavado"),           # Lavadoras, Secadoras
    ("679/690",  "Cocinas"),          # Cocinas, Hornos
    ("679/694",  "Electrodomésticos"),# Licuadoras, Aspiradoras, etc.
    ("679/696",  "Climatización"),    # Aires acondicionados, Ventiladores
    # --- Moda y Calzado (nivel 1) ---
    ("3072", "Zapatillas"),
    ("3086", "Zapatos"),
    ("3174", "Moda Hombre"),
    ("3201", "Moda Mujer"),
    ("2941", "Moda Infantil"),
    # --- Deporte (nivel 1) ---
    ("1105", "Deportes"),
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
    """Extrae la categoría más descriptiva del path VTEX.

    VTEX devuelve una lista ordenada de más específica a menos específica:
      ['/Tecnología/Televisores/TV LED/', '/Tecnología/Televisores/', '/Tecnología/']

    Usamos nivel 2 (ej. 'Televisores') porque:
    - Nivel 1 ('Tecnología') es demasiado amplio
    - Nivel 3 ('TV LED') es demasiado granular para filtros
    """
    if not vtex_categories:
        return fallback
    # El primer elemento es el más específico
    path = vtex_categories[0]
    parts = [p.strip() for p in path.split("/") if p.strip()]
    # parts = ['Tecnología', 'Televisores', 'TV LED']
    if len(parts) >= 2:
        return parts[1]   # subcategoría principal
    if parts:
        return parts[0]   # solo departamento si no hay sub
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

        # Categoría extraída del path real del producto
        category = _extract_category(p.get("categories") or [], fallback_category)

        out.append(ScrapedProduct(
            name=name,
            brand=str(p.get("brand") or ""),
            store="plazavea",
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


class PlazaVeaScraper(BaseScraper):
    store = "plazavea"

    async def _scrape_top_deals(self, client: httpx.AsyncClient) -> list[ScrapedProduct]:
        """Top descuentos de PlazaVea sin filtro de categoría."""
        results: list[ScrapedProduct] = []
        for page in range(_TOP_DEALS_PAGES):
            start = page * _PAGE_SIZE
            end = start + _PAGE_SIZE - 1
            params = {"_from": start, "_to": end, "O": "OrderByBestDiscountDESC"}
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

                # 2. Categorías específicas sin duplicar
                seen_skus = {p.store_sku for p in all_products}
                for cat_id, cat_name in _CATEGORIES:
                    for page in range(_MAX_PAGES):
                        start = page * _PAGE_SIZE
                        end = start + _PAGE_SIZE - 1
                        params = {
                            "fq": f"C:/{cat_id}/",
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
                        new_items = [i for i in items if i.store_sku not in seen_skus]
                        seen_skus.update(i.store_sku for i in new_items)
                        all_products.extend(new_items)
                        await asyncio.sleep(0.5)
                        if len(data) < _PAGE_SIZE:
                            break
        except Exception as exc:
            raise ScraperError(f"PlazaVea get_category error: {exc}") from exc
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
            raise ScraperError(f"PlazaVea search error: {exc}") from exc

    async def get_product_detail(self, url: str) -> ScrapedProduct:
        raise NotImplementedError
