from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation

import httpx

from app.scrapers.base import BaseScraper, ScrapedProduct, ScraperError, now_utc
from app.scrapers.stealth import random_user_agent

_BASE = "https://www.shopstar.pe"
_API = f"{_BASE}/api/catalog_system/pub/products/search"
_PAGE_SIZE = 50
_MAX_PAGES = 10  # hasta 500 productos por categoría
_TOP_DEALS_PAGES = 6  # 300 productos con mayor descuento sin filtro de categoría
# VTEX corta con HTTP 400 cuando _from supera 2500 — no pedir más allá de ese offset.
_MAX_OFFSET = 2500

# (fq_path, fallback_name) — paths con trailing slash obligatorio, igual que Oechsle.
# NO se incluye Supermercado (1394): el seller por defecto de Shopstar es Plaza Vea,
# así que ese árbol duplicaría el catálogo que ya trae el scraper de plazavea.
# Tampoco se incluyen Navidad (estacional), Vales/Gift cards (no son productos físicos),
# Regalo (1545, son rangos de precio que solapan todo) ni las categorías TEST-*/prueba.
_CATEGORIES: list[tuple[str, str]] = [
    # --- Tecnología (padre 443) ---
    ("443/449/",   "Televisores"),
    ("443/477/",   "Computo"),
    ("443/551/",   "Telefonía"),
    ("443/602/",   "Audio"),
    ("443/669/",   "Cámaras"),
    ("443/694/",   "Videojuegos"),
    ("443/1517/",  "Smart Home"),
    ("443/2248/",  "Proyectores"),
    # --- Electrohogar (padre 441) ---
    ("441/442/",   "Refrigeración"),
    ("441/445/",   "Lavado"),
    ("441/446/",   "Electrodomésticos"),
    ("441/448/",   "Cocina"),
    ("441/521/",   "Climatización"),
    ("441/2217/",  "Aspirado"),
    # --- Muebles (padre 444) ---
    ("444/447/",   "Sala"),
    ("444/450/",   "Comedor"),
    ("444/455/",   "Oficina"),
    ("444/459/",   "Dormitorio"),
    # --- Hogar (padre 536) ---
    ("536/537/",   "Decoración"),
    ("536/538/",   "Menaje Cocina"),
    ("536/548/",   "Maletas y Viajes"),
    ("536/557/",   "Iluminación"),
    ("536/994/",   "Cocina"),
    # --- Dormitorio (padre 539) ---
    ("539/540/",   "Colchones"),
    ("539/549/",   "Ropa de Cama"),
    # --- Deportes y aire libre (padre 577) ---
    ("577/609/",   "Fitness"),
    ("577/612/",   "Bicicletas"),
    ("577/615/",   "Camping"),
    ("577/1639/",  "Deportes"),
    # --- Calzado (padre 624) ---
    ("624/626/",   "Calzado Mujer"),
    ("624/630/",   "Calzado Hombre"),
    ("624/632/",   "Zapatillas Mujer"),
    ("624/634/",   "Zapatillas Hombre"),
    # --- Infantil (padre 703) ---
    ("703/708/",   "Mundo Bebé"),
    ("703/711/",   "Juguetes"),
    ("703/1003/",  "Escolar"),
    # --- Moda (padre 716) ---
    ("716/757/",   "Moda Mujer"),
    ("716/768/",   "Moda Hombre"),
    # --- Mascotas (padre 562) ---
    ("562/723/",   "Perros"),
    ("562/727/",   "Gatos"),
    # --- Belleza y cuidado personal (padre 801) ---
    ("801/824/",   "Maquillaje"),
    ("801/1364/",  "Cuidado Personal"),
    ("801/1365/",  "Cuidado de la Piel"),
    ("801/1382/",  "Perfumería"),
    ("801/1445/",  "Cuidado del Cabello"),
    ("801/1606/",  "Aparatos Eléctricos"),
    # --- Automóvil (padre 802) ---
    ("802/803/",   "Accesorios Auto"),
    # --- Construcción y herramientas (padre 826) ---
    ("826/830/",   "Pinturas"),
    ("826/838/",   "Electricidad"),
    ("826/839/",   "Herramientas"),
    # --- Accesorios de moda (padre 1444) ---
    ("1444/828/",  "Relojes"),
    ("1444/834/",  "Carteras"),
    ("1444/840/",  "Lentes"),
    ("1444/848/",  "Mochilas"),
    ("1444/1027/", "Joyas"),
    # --- Salud y bienestar (padre 1458) ---
    ("1458/1460/", "Nutrición Deportiva"),
    ("1458/1463/", "Vitaminas"),
    # --- Mundo Geek (padre 2118) ---
    ("2118/2119/", "Coleccionables"),
    ("2118/2120/", "Funkos"),
    ("2118/2121/", "Juegos de Mesa"),
    ("2118/2122/", "Lego"),
    # --- Libros, útiles y oficina (padre 1427) ---
    ("1427/2225/", "Útiles Escolares"),
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


def _pick_offer(item: dict) -> dict:
    """Devuelve la commertialOffer del seller válido.

    Shopstar es un marketplace: un item trae varios sellers y el que NO vende
    (p.ej. "Mercury") viene con Price 0. Tomar sellers[0] a ciegas descartaría
    el producto, así que se prioriza el sellerDefault y se cae al primero con precio.
    """
    sellers = item.get("sellers") or []
    if not sellers:
        return {}
    for s in sellers:
        if s.get("sellerDefault") and _parse_price((s.get("commertialOffer") or {}).get("Price")) > 0:
            return s.get("commertialOffer") or {}
    for s in sellers:
        if _parse_price((s.get("commertialOffer") or {}).get("Price")) > 0:
            return s.get("commertialOffer") or {}
    return sellers[0].get("commertialOffer") or {}


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
        co = _pick_offer(item)
        if not co:
            continue

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
        url = p.get("link") or (f"{_BASE}/{link_text}/p" if link_text else "")

        category = _extract_category(p.get("categories") or [], fallback_category)

        out.append(ScrapedProduct(
            name=name,
            brand=str(p.get("brand") or ""),
            store="shopstar",
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


class ShopstarScraper(BaseScraper):
    store = "shopstar"

    async def _scrape_top_deals(self, client: httpx.AsyncClient) -> list[ScrapedProduct]:
        """Raspa los mejores descuentos de Shopstar sin filtro de categoría."""
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
                # 1. Top deals generales (captura ofertas fuera de las categorías mapeadas)
                top_deals = await self._scrape_top_deals(client)
                all_products.extend(top_deals)

                # 2. Categorías específicas
                seen_skus = {p.store_sku for p in all_products}
                for fq_path, cat_name in _CATEGORIES:
                    for page in range(_MAX_PAGES):
                        start = page * _PAGE_SIZE
                        if start > _MAX_OFFSET:
                            break
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
                        # Evitar duplicados con los top deals y entre categorías
                        new_items = [i for i in items if i.store_sku not in seen_skus]
                        seen_skus.update(i.store_sku for i in new_items)
                        all_products.extend(new_items)
                        await asyncio.sleep(0.5)
                        if len(data) < _PAGE_SIZE:
                            break
        except Exception as exc:
            raise ScraperError(f"Shopstar get_category error: {exc}") from exc
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
            raise ScraperError(f"Shopstar search error: {exc}") from exc

    async def get_product_detail(self, url: str) -> ScrapedProduct:
        raise NotImplementedError
