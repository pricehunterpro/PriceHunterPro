from __future__ import annotations

import asyncio
import hashlib
import re
from decimal import Decimal, InvalidOperation

import httpx
from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper, ScrapedProduct, ScraperError, now_utc
from app.scrapers.stealth import random_user_agent

_BASE = "https://www.mercadolibre.com.pe"
_OFERTAS = f"{_BASE}/ofertas"
_MAX_PAGES = 25  # 40 productos/página → ~1000 ofertas


def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={
            "User-Agent": random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "es-PE,es;q=0.9,en-US;q=0.8,en;q=0.7",
        },
        follow_redirects=True,
        timeout=30,
    )


def _money(el) -> Decimal:
    """Lee un monto de un contenedor .andes-money-amount (fracción + centavos)."""
    if el is None:
        return Decimal("0")
    frac = el.select_one(".andes-money-amount__fraction")
    if frac is None:
        return Decimal("0")
    digits = re.sub(r"[^\d]", "", frac.get_text())
    cents_el = el.select_one(".andes-money-amount__cents")
    cents = re.sub(r"[^\d]", "", cents_el.get_text()) if cents_el else ""
    raw = f"{digits}.{cents}" if cents else digits
    try:
        return Decimal(raw) if digits else Decimal("0")
    except InvalidOperation:
        return Decimal("0")


def _sku_from(url: str, image: str) -> str:
    """Identificador estable y ÚNICO por producto.
    Prioriza el ID de catálogo (/p/MPE...) o de artículo (MPE-/MLM-1234...),
    si no, usa un hash de la URL limpia (garantiza unicidad)."""
    base = url.split("?")[0].split("#")[0]
    m = re.search(r"/p/([A-Z]{2,4}\d{6,})", base)
    if m:
        return m.group(1)
    m = re.search(r"(ML[A-Z]|MPE)-?(\d{9,})", base)
    if m:
        return m.group(1) + m.group(2)
    if base:
        return "ml" + hashlib.md5(base.encode()).hexdigest()[:14]
    return "ml" + hashlib.md5((image or "x").encode()).hexdigest()[:14]


def _parse_cards(html: str) -> list[ScrapedProduct]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".poly-card")
    out: list[ScrapedProduct] = []
    for card in cards:
        title_el = card.select_one(".poly-component__title")
        if title_el is None:
            continue
        name = title_el.get_text(strip=True)
        if not name:
            continue

        link_el = card.select_one("a.poly-component__title") or card.select_one("a[href]")
        url = link_el.get("href", "") if link_el else ""
        if url and not url.startswith("http"):
            url = _BASE + url

        current_price = _money(card.select_one(".poly-price__current"))
        original_price = _money(card.select_one(".andes-money-amount--previous"))
        if current_price == Decimal("0"):
            continue
        if original_price < current_price:
            original_price = current_price

        discount = Decimal("0")
        if original_price > current_price:
            discount = ((original_price - current_price) / original_price * 100).quantize(Decimal("0.01"))

        img_el = card.select_one("img")
        image_url = ""
        if img_el:
            image_url = img_el.get("data-src") or img_el.get("src") or ""

        brand_el = card.select_one(".poly-component__brand")
        brand = brand_el.get_text(strip=True) if brand_el else ""

        out.append(ScrapedProduct(
            name=name,
            brand=brand,
            store="mercadolibre",
            store_sku=_sku_from(url, image_url),
            url=url,
            current_price=current_price,
            original_price=original_price,
            discount_percentage=discount,
            in_stock=True,  # la página de ofertas solo lista productos comprables
            image_url=str(image_url),
            category="Ofertas",
            scraped_at=now_utc(),
        ))
    return out


class MercadoLibreScraper(BaseScraper):
    store = "mercadolibre"

    async def get_category(self, category_url: str = "") -> list[ScrapedProduct]:
        all_products: list[ScrapedProduct] = []
        seen: set[str] = set()
        try:
            async with _make_client() as client:
                for page in range(1, _MAX_PAGES + 1):
                    url = f"{_OFERTAS}?page={page}"
                    try:
                        r = await client.get(url)
                    except Exception:
                        break
                    if r.status_code != 200:
                        break
                    items = _parse_cards(r.content.decode("utf-8", errors="replace"))
                    if not items:
                        break
                    new_items = [i for i in items if i.store_sku not in seen]
                    seen.update(i.store_sku for i in new_items)
                    all_products.extend(new_items)
                    await asyncio.sleep(0.6)
                    if len(items) < 20:
                        break
        except Exception as exc:
            raise ScraperError(f"MercadoLibre get_category error: {exc}") from exc
        return all_products

    async def search_products(self, query: str) -> list[ScrapedProduct]:
        try:
            async with _make_client() as client:
                r = await client.get(f"{_BASE}/ofertas", params={"q": query})
                if r.status_code != 200:
                    return []
                return _parse_cards(r.content.decode("utf-8", errors="replace"))
        except Exception as exc:
            raise ScraperError(f"MercadoLibre search error: {exc}") from exc

    async def get_product_detail(self, url: str) -> ScrapedProduct:
        raise NotImplementedError
