from __future__ import annotations

import asyncio
import json
import random
import re
from decimal import Decimal, InvalidOperation

import httpx
from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper, ScrapedProduct, ScraperError, now_utc
from app.scrapers.stealth import random_user_agent

# OJO: Tottus NO es VTEX. `/api/catalog_system/pub/products/search` devuelve 403
# (era el endpoint del scraper anterior, por eso la tienda figuraba "bloqueada").
# Tottus corre sobre la MISMA plataforma que Falabella (Catalyst / Next.js), así
# que los productos vienen en el `__NEXT_DATA__` del SSR, igual que falabella_scraper.
#
# Rutas verificadas (2026-08-07):
#   /tottus-pe/lista/CATGxxxxx/Slug?page=N  -> 200, listado paginado (48 por página)
#   /tottus-pe/buscar?Ntt=<query>           -> 200, búsqueda
#   /tottus-pe/category/...                 -> 503 (esa ruta NO existe en Tottus)
_BASE = "https://www.tottus.com.pe/tottus-pe"
_PER_PAGE = 48
# Dormitorio (la más grande) tiene ~1.375 productos = 29 páginas. El corte real
# lo hace la página vacía; esto es solo un tope de seguridad.
_MAX_PAGES = 32

# Categorías L1: cada una ya incluye a todos sus descendientes, por eso no hace
# falta recorrer las subcategorías (el árbol completo sale de
# `serverData.headerData.taxonomy` en el HTML del home).
# Se omiten a propósito las ramas de supermercado perecible/abarrotes (carnes,
# lácteos, panadería, snacks, etc.): son productos de S/ 3-15 que el pipeline de
# alertas descarta igual (filtra current_price >= 50) y solo meterían ruido.
_CATEGORY_SLUGS: list[tuple[str, str]] = [
    # Tecnología y electrohogar
    ("CATG48292/Tecnologia", "Tecnología"),
    ("CATG48293/Electrohogar", "Electrohogar"),
    # Hogar
    ("CATG48294/Dormitorio", "Dormitorio"),
    ("CATG48296/Muebles", "Muebles"),
    ("CATG48295/Menaje-y-Organizacion", "Menaje y Organización"),
    # Moda y bazar
    ("CATG48300/Vestuario", "Vestuario"),
    ("CATG48299/Bazar", "Bazar"),
    ("CATG48298/Deportes-y-Aire-Libre", "Deportes"),
    ("CATG48297/Jugueteria", "Juguetería"),
    # Belleza y cuidado personal
    ("CATG16057/Belleza", "Belleza"),
    ("CATG44261/Cuidado-Capilar", "Cuidado Capilar"),
    ("CATG16072/Cuidado-Personal", "Cuidado Personal"),
    ("CATG16073/Mundo-Bebes", "Bebés y Niños"),
    # Hogar consumible y mascotas
    ("CATG16051/Limpieza", "Limpieza"),
    ("CATG16055/Mundo-Mascotas", "Mascotas"),
    # Licores: ticket alto y descuentos reales (whisky, vinos, cervezas)
    ("CATG16069/Bebidas-Alcoholicas", "Licores"),
    ("CATG16070/Cervezas", "Cervezas"),
]


def _make_client() -> httpx.AsyncClient:
    # Solo User-Agent — igual que Falabella: cabeceras de API extra activan una
    # ruta del CDN que devuelve el HTML sin resultados.
    return httpx.AsyncClient(
        headers={"User-Agent": random_user_agent()},
        follow_redirects=True,
        timeout=30,
    )


async def _get_next_data(client: httpx.AsyncClient, url: str) -> dict:
    """Descarga la página y devuelve el JSON de `__NEXT_DATA__` ({} si falla).

    Reintenta ante 5xx y errores de red: en pruebas ~1 de cada 10 peticiones
    corta la conexión sin motivo aparente.
    """
    for attempt in range(3):
        try:
            r = await client.get(url)
            if r.status_code >= 500:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code != 200:
                return {}
            html = r.content.decode("utf-8", errors="replace")
            soup = BeautifulSoup(html, "html.parser")
            tag = soup.find("script", id="__NEXT_DATA__")
            return json.loads(tag.string) if tag else {}
        except Exception:
            await asyncio.sleep(1.5 * (attempt + 1))
    return {}


def _parse_price(raw: str | list) -> Decimal:
    """Convierte los formatos de precio de Tottus a Decimal.
    Formatos: '2,139' / ['2,139'] / '29.90'

    Si `raw` es lista con varios elementos se toma solo el primero (concatenarlos
    generaba precios basura, mismo bug que en Falabella).
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

        # Precio actual por prioridad: internetPrice > eventPrice > cmrPrice.
        # cmrPrice va al final porque exige tarjeta CMR (no es precio público).
        prices_by_type: dict[str, Decimal] = {}
        original_price = Decimal("0")
        for p in item.get("prices") or []:
            val = _parse_price(p.get("price", []))
            ptype = p.get("type", "")
            if ptype and val > Decimal("0") and ptype not in prices_by_type:
                prices_by_type[ptype] = val
            # El precio tachado (`normalPrice`) es el precio lista
            if p.get("crossed", False) and original_price == Decimal("0"):
                original_price = val

        current_price = Decimal("0")
        for pref in ("internetPrice", "eventPrice", "cmrPrice"):
            if pref in prices_by_type:
                current_price = prices_by_type[pref]
                break

        # El precio CMR se guarda APARTE del público. Es exactamente el caso de la
        # laptop HP Victus del 15/07: CMR S/499 con precio internet S/3.139. Si solo
        # guardamos el internet, el glitch queda invisible.
        card_price = prices_by_type.get("cmrPrice")

        if current_price == Decimal("0"):
            continue
        if original_price < current_price:
            original_price = current_price

        # El descuento se CALCULA, no se toma de `discountBadge`: el badge de
        # Tottus se arma contra el precio más bajo incluyendo CMR (p. ej. iPad
        # normal 1699 / internet 1599 / cmr 1549 muestra "-9%" cuando contra el
        # precio que guardamos son 5,9%). Usar el badge inflaba el descuento.
        discount = Decimal("0")
        if original_price > current_price:
            discount = ((original_price - current_price) / original_price * 100).quantize(Decimal("0.01"))

        media = item.get("mediaUrls") or []
        image_url = media[0] if media else ""

        # El listado solo devuelve productos comprables; `availability` trae al
        # menos una modalidad de entrega con texto cuando hay stock.
        availability = item.get("availability") or {}
        in_stock = any(str(v).strip() for v in availability.values())

        out.append(ScrapedProduct(
            name=name,
            brand=str(item.get("brand") or ""),
            store="tottus",
            store_sku=str(item.get("skuId") or item.get("productId") or ""),
            url=str(item.get("url") or ""),
            current_price=current_price,
            original_price=original_price,
            discount_percentage=discount,
            in_stock=in_stock,
            image_url=str(image_url),
            category=category,
            scraped_at=now_utc(),
            card_price=card_price,
        ))
    return out


class TottusScraper(BaseScraper):
    store = "tottus"

    async def get_category(self, category_url: str = "") -> list[ScrapedProduct]:
        all_products: list[ScrapedProduct] = []
        try:
            async with _make_client() as client:
                seen_skus: set[str] = set()
                for slug, cat_name in _CATEGORY_SLUGS:
                    # OJO: la guarda anti-bucle se mide contra los SKUs vistos EN
                    # ESTA categoría, no contra el set global. Las ramas se solapan
                    # (un shampoo está en Belleza y en Cuidado Capilar); con el set
                    # global una página repetida cortaba la paginación a medias y se
                    # perdía el resto de la categoría.
                    cat_seen: set[str] = set()
                    for page_num in range(1, _MAX_PAGES + 1):
                        url = f"{_BASE}/lista/{slug}?page={page_num}"
                        data = await _get_next_data(client, url)
                        results = (data.get("props") or {}).get("pageProps", {}).get("results") or []
                        if not results:
                            break

                        # Guarda anti-bucle: si la página no trae SKUs nuevos, el
                        # sitio nos devolvió contenido repetido → cortar.
                        page_skus = {
                            str(r.get("skuId") or r.get("productId") or "") for r in results
                        }
                        if page_skus and page_skus <= cat_seen:
                            break
                        cat_seen |= page_skus

                        # Dedup global: Tottus repite SKUs entre páginas de una
                        # misma categoría (~24% en Dormitorio) y entre ramas.
                        for p in _products_from_results(results, cat_name):
                            if p.store_sku in seen_skus:
                                continue
                            seen_skus.add(p.store_sku)
                            all_products.append(p)

                        # Pausa aleatoria para no marcar un patrón de scraping
                        await asyncio.sleep(random.uniform(0.4, 1.0))
                        if len(results) < _PER_PAGE:
                            break
        except Exception as exc:
            raise ScraperError(f"Tottus get_category error: {exc}") from exc
        return all_products

    async def search_products(self, query: str) -> list[ScrapedProduct]:
        try:
            async with _make_client() as client:
                url = str(httpx.URL(f"{_BASE}/buscar", params={"Ntt": query}))
                data = await _get_next_data(client, url)
                page_props = (data.get("props") or {}).get("pageProps", {})
                results = page_props.get("results") or []
                items = _products_from_results(results, "Búsqueda")

                # Cuando la búsqueda exacta no encuentra nada, Tottus cae a una
                # búsqueda vectorial y devuelve 48 productos SIN relación (para
                # "xbox series x" contesta televisores y gaseosas). Se detecta con
                # `metadata.vectorSearchApplied` y en ese caso se exige que el
                # nombre contenga alguna palabra de la consulta.
                if (page_props.get("metadata") or {}).get("vectorSearchApplied"):
                    tokens = [t for t in re.split(r"\W+", query.lower()) if len(t) >= 3]
                    if tokens:
                        items = [p for p in items if any(t in p.name.lower() for t in tokens)]
                return items
        except Exception as exc:
            raise ScraperError(f"Tottus search error: {exc}") from exc

    async def get_product_detail(self, url: str) -> ScrapedProduct:
        raise NotImplementedError
