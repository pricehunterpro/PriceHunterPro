from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal


@dataclass
class ScrapedProduct:
    name: str
    brand: str
    store: str
    store_sku: str
    url: str
    current_price: Decimal
    original_price: Decimal
    discount_percentage: Decimal
    in_stock: bool
    image_url: str
    category: str
    scraped_at: datetime


class BaseScraper:
    async def search_products(self, query: str) -> list[ScrapedProduct]:
        raise NotImplementedError

    async def get_product_detail(self, url: str) -> ScrapedProduct:
        raise NotImplementedError

    async def get_category(self, category_url: str) -> list[ScrapedProduct]:
        raise NotImplementedError


class ScraperError(RuntimeError):
    """Raised when a scraper cannot process a request."""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
