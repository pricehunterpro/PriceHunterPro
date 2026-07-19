from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation

import httpx
from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper, ScrapedProduct, ScraperError, now_utc
from app.scrapers.stealth import random_user_agent

_BASE = "https://www.falabella.com.pe/falabella-pe"
_MAX_PAGES = 5

_CATEGORY_SLUGS = [
    # Tecnología
    "/category/cat40712/Laptops",
    "/category/cat50678/Computadoras",
    "/category/cat210477/TV-Televisores",
    "/category/cat760706/Celulares-y-Telefonos",
    "/category/cat270476/Tablets",
    "/category/cat800582/Audifonos",
    "/category/cat800584/Parlantes-Bluetooth",
    "/category/cat40556/Videojuegos",
    "/category/cat1830468/Smartwatch-y-wearables",
    "/category/cat3180533/Impresoras",
    # Computación — subcategorías que faltaban (viven bajo Computadoras/cat50678,
    # que solo con 5 páginas no alcanzaba; aquí p. ej. está el marketplace de
    # soportes/periféricos que antes no capturábamos).
    "/category/cat40509/Accesorios-Computacion-y-Perifericos",
    "/category/cat40695/Monitores",
    "/category/cat40480/Almacenamiento",
    "/category/cat16470475/Computadores-de-escritorio",
    "/category/cat1590484/All-in-one",
    # Electrohogar
    "/category/CATG19032/Refrigeracion",
    "/category/cat780522/Lavadoras",
    "/category/cat7180470/Lavadora-Secadora",
    "/category/cat780524/Secadora-de-ropa",
    "/category/cat40691/Microondas",
    "/category/cat40690/Cocinas",
    "/category/CATG19033/Linea-blanca",
    # Calzado y Moda
    "/category/cat1470548/Zapatillas",
    "/category/cat1470534/Zapatillas-urbanas-mujer",
    "/category/CATG15651/Zapatillas-deportivas-hombre",
    "/category/CATG34381/Zapatillas-de-futbol",
    "/category/CATG15668/Pijamas",
    "/category/CATG12009/Ropa-deportiva",
    # Juguetería y Bebés
    "/category/CATG34943/Jugueteria",
    "/category/cat11510475/Moda-Infantil",
    "/category/cat11810546/Lego-y-Armables",
    "/category/cat40497/Mundo-Bebe",
    # Belleza y Salud
    "/category/CATG11985/Cuidado-de-la-piel",
    "/category/CATG14388/Vitaminas",
    "/category/cat11140487/Dermocosmetica",
    # Deportes
    "/category/cat40500/Bicicletas",
    "/category/CATG34932/Lentes-de-sol",
    "/category/CATG15650/Relojes-mujer",
    "/category/CATG15657/Relojes-hombre",
    # Categorías L0 amplias (verificadas por facets) — cubren accesorios de moda
    # (gorras/chullos/mochilas), moda general, deportes, belleza, hogar y viajes.
    "/category/CATG46360/Accesorios-Moda",
    "/category/CATG11950/Moda",
    "/category/cat40571/Deportes-y-aire-libre",
    "/category/cat40498/Belleza-higiene-y-salud",
    "/category/CATG11947/Decohogar",
    "/category/CATG34914/Maleteria-y-viajes",
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
        if r.status_code != 200:
            return {}
        html = r.content.decode("utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        tag = soup.find("script", id="__NEXT_DATA__")
        return json.loads(tag.string) if tag else {}
    except Exception:
        return {}


def _parse_price(raw: str | list) -> Decimal:
    """Convert Falabella price formats to Decimal.
    Formats: '2,399' / ['2,399'] / 'S/ 2,399.90'

    OJO: cuando `raw` es una lista con varios elementos (p. ej. ['1,599','1,619'])
    NO se deben concatenar — hacerlo producía precios basura ('15991619').
    Se toma solo el primer elemento (el precio principal mostrado).
    """
    if isinstance(raw, list):
        raw = str(raw[0]) if raw else ""
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

        # Prices — se recogen por tipo y se elige el precio actual por prioridad.
        # internetPrice (precio online) > eventPrice (oferta) > cmrPrice (tarjeta CMR).
        prices_by_type: dict[str, Decimal] = {}
        original_price = Decimal("0")
        for p in item.get("prices") or []:
            val = _parse_price(p.get("price", []))
            ptype = p.get("type", "")
            if ptype and val > Decimal("0") and ptype not in prices_by_type:
                prices_by_type[ptype] = val
            if p.get("crossed", False) and original_price == Decimal("0"):
                original_price = val

        current_price = Decimal("0")
        for pref in ("internetPrice", "eventPrice", "cmrPrice"):
            if pref in prices_by_type:
                current_price = prices_by_type[pref]
                break

        if current_price == Decimal("0"):
            continue
        if original_price < current_price:
            original_price = current_price

        # Discount from badge or calculated
        discount = Decimal("0")
        badge_label = (item.get("discountBadge") or {}).get("label", "")
        pct_str = re.sub(r"[^\d]", "", badge_label)
        if pct_str:
            discount = Decimal(pct_str)
        elif original_price > Decimal("0"):
            discount = ((original_price - current_price) / original_price * 100).quantize(Decimal("0.01"))

        media = item.get("mediaUrls") or []
        image_url = media[0] if media else ""

        # in_stock: stickers=Falabella direct, badge=promo activa, precio<original=marketplace deal
        stickers = item.get("meatStickers") or []
        in_stock = len(stickers) > 0 or bool(badge_label) or (original_price > current_price)

        out.append(ScrapedProduct(
            name=name,
            brand=str(item.get("brand") or ""),
            store="falabella",
            store_sku=str(item.get("skuId") or item.get("productId") or ""),
            url=str(item.get("url") or ""),
            current_price=current_price,
            original_price=original_price,
            discount_percentage=discount,
            in_stock=in_stock,
            image_url=str(image_url),
            category=category,
            scraped_at=now_utc(),
        ))
    return out


class FalabellaScraper(BaseScraper):
    store = "falabella"

    async def get_category(self, category_url: str = "") -> list[ScrapedProduct]:
        all_products: list[ScrapedProduct] = []
        try:
            async with _make_client() as client:
                for slug in _CATEGORY_SLUGS:
                    raw = slug.split("/")[-1]
                    cat_name = raw.replace("-y-", " y ").replace("-", " ").title()
                    seen_skus: set[str] = set()
                    for page_num in range(1, _MAX_PAGES + 1):
                        # OJO: el parámetro de paginación real es `page`, NO `currentPage`.
                        # Con `currentPage` el sitio devolvía SIEMPRE la página 1 → las
                        # páginas 2..N eran duplicados que colapsaban a ~1 página útil por
                        # categoría (inflaba `saved` ~6x sin aportar productos). sortBy
                        # rompe el SSR — se omite; DealService ordena en cliente.
                        url = f"{_BASE}{slug}?page={page_num}"
                        data = await _get_next_data(client, url)
                        results = (data.get("props") or {}).get("pageProps", {}).get("results") or []
                        if not results:
                            break
                        # Guarda anti-bucle: si la página no trae SKUs nuevos (el sitio
                        # volvió a la 1 al pasarnos del total), dejamos de paginar.
                        page_skus = {
                            str(r.get("skuId") or r.get("productId") or "") for r in results
                        }
                        if page_skus and page_skus <= seen_skus:
                            break
                        seen_skus |= page_skus
                        items = _products_from_results(results, cat_name)
                        all_products.extend(items)
                        # Stop paginating if we got a partial page
                        if len(results) < 20:
                            break
        except Exception as exc:
            raise ScraperError(f"Falabella get_category error: {exc}") from exc
        return all_products

    async def search_products(self, query: str) -> list[ScrapedProduct]:
        try:
            async with _make_client() as client:
                url = f"{_BASE}/search?Ntt={query}"
                data = await _get_next_data(client, url)
                results = (data.get("props") or {}).get("pageProps", {}).get("results") or []
                return _products_from_results(results, "Búsqueda")
        except Exception as exc:
            raise ScraperError(f"Falabella search error: {exc}") from exc

    async def get_product_detail(self, url: str) -> ScrapedProduct:
        raise NotImplementedError
