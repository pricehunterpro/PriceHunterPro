from __future__ import annotations

import asyncio
import re
from decimal import Decimal, InvalidOperation

import httpx
from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper, ScrapedProduct, now_utc
from app.scrapers.stealth import random_user_agent

_BASE = "https://hiraoka.com.pe"
_MAX_PAGES = 15  # 20 productos por página → hasta 300 por categoría

# Magento: el listado es HTML (no hay API pública). Paginación con ?p=N; una página
# fuera de rango devuelve 0 productos. Solo se listan categorías hoja de producto
# físico (se omiten blog, marcas, calendario y landings que duplican catálogo).
_CATEGORIES: list[tuple[str, str]] = [
    ("electrohogar/refrigeracion", "Refrigeración"),
    ("electrohogar/lavado-y-limpieza", "Lavado"),
    ("electrohogar/electrodomesticos", "Electrodomésticos"),
    ("electrohogar/cocina-y-empotrables", "Cocina"),
    ("electrohogar/menaje", "Menaje"),
    ("electrohogar/herramientas", "Herramientas"),
    ("climatizacion/aire-acondicionado", "Climatización"),
    ("climatizacion/ventiladores", "Climatización"),
    ("climatizacion/termas-y-rapiduchas", "Climatización"),
    ("climatizacion/estufas", "Climatización"),
    ("televisores", "Televisores"),
    ("audio-y-musica/audio", "Audio"),
    ("audio-y-musica/audifonos", "Audio"),
    ("celulares-y-telefonia/celulares", "Celulares"),
    ("celulares-y-telefonia/smartwatch", "Smartwatch"),
    ("computo-y-tablets/computadoras", "Cómputo"),
    ("computo-y-tablets/tablets", "Tablets"),
    ("computo-y-tablets/monitores", "Monitores"),
    ("computo-y-tablets/impresoras-y-tintas", "Impresoras"),
    ("computo-y-tablets/proyectores", "Proyectores"),
    ("gaming/consolas", "Videojuegos"),
    ("gaming/computo-gaming", "Gaming"),
    ("gaming/accesorios-gaming", "Gaming"),
    ("camaras-y-drones/camaras-digitales", "Cámaras"),
    ("camaras-y-drones/drones", "Cámaras"),
    ("dormitorio/colchones", "Colchones"),
    ("dormitorio/camas", "Dormitorio"),
    ("deportes/bicicletas", "Bicicletas"),
    ("deportes/maquinas-de-deportes", "Fitness"),
    ("smarthome/camaras", "Smart Home"),
    ("relojes/relojes-casuales", "Relojes"),
    ("salud-y-bienestar/cuidado-personal", "Cuidado Personal"),
]


def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": random_user_agent()},
        follow_redirects=True,
        timeout=30,
    )


def _price(node) -> Decimal:
    if node is None:
        return Decimal("0")
    try:
        return Decimal(str(node.get("data-price-amount") or "0"))
    except InvalidOperation:
        return Decimal("0")


def _parse_listing(html: str, category: str) -> list[ScrapedProduct]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[ScrapedProduct] = []
    for li in soup.select("li.product-item"):
        link = li.select_one("strong.product-item-name a")
        if not link:
            continue
        name = (link.get("title") or link.get_text()).strip()
        url = link.get("href") or ""

        current = _price(li.select_one('[data-price-type="finalPrice"]'))
        if current <= 0 or not name:
            continue
        original = _price(li.select_one('[data-price-type="oldPrice"]'))
        if original < current:
            original = current
        discount = Decimal("0")
        if original > current:
            discount = ((original - current) / original * 100).quantize(Decimal("0.01"))

        sku_el = li.select_one("strong.product-item-sku")
        sku_txt = sku_el.get_text(" ", strip=True) if sku_el else ""
        m = re.search(r"(\d+)", sku_txt)
        sku = m.group(1) if m else url.rstrip("/").rsplit("/", 1)[-1]

        brand_el = li.select_one("strong.product-item-brand")
        img = li.select_one("img.product-image-photo")
        image_url = (img.get("src") or "") if img else ""
        # El src trae parámetros de recorte 240x300; la imagen base es la original.
        image_url = image_url.split("?", 1)[0]

        out.append(ScrapedProduct(
            name=name,
            brand=brand_el.get_text(strip=True) if brand_el else "",
            store="hiraoka",
            store_sku=sku,
            url=url,
            current_price=current,
            original_price=original,
            discount_percentage=discount,
            in_stock=bool(li.select_one("button.tocart, .action.tocart")),
            image_url=image_url,
            category=category,
            scraped_at=now_utc(),
        ))
    return out


class HiraokaScraper(BaseScraper):
    store = "hiraoka"

    async def search_products(self, query: str) -> list[ScrapedProduct]:
        async with _make_client() as client:
            r = await client.get(f"{_BASE}/catalogsearch/result/", params={"q": query})
            return _parse_listing(r.text, "Búsqueda") if r.status_code == 200 else []

    async def get_category(self, category_url: str = "") -> list[ScrapedProduct]:
        all_products: list[ScrapedProduct] = []
        seen: set[str] = set()
        async with _make_client() as client:
            for path, cat_name in _CATEGORIES:
                for page in range(1, _MAX_PAGES + 1):
                    try:
                        r = await client.get(f"{_BASE}/{path}", params={"p": page})
                    except httpx.RequestError:
                        break
                    if r.status_code != 200:
                        break
                    items = _parse_listing(r.text, cat_name)
                    nuevos = [p for p in items if p.store_sku not in seen]
                    if not nuevos:
                        break
                    seen.update(p.store_sku for p in nuevos)
                    all_products.extend(nuevos)
                    await asyncio.sleep(0.5)
        return all_products
