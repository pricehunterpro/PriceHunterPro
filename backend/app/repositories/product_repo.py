from __future__ import annotations

import re
import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import PriceHistory, Product, ScrapingLog, StoreProduct
from app.scrapers.base import ScrapedProduct


def _normalize_sku(name: str, brand: str) -> str:
    base = f"{brand.strip()}-{name.strip()}".lower()
    return re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:100]


def upsert_scraped_product(session: Session, scraped: ScrapedProduct) -> StoreProduct:
    """Upsert Product + StoreProduct; append PriceHistory when price changes."""
    sku = _normalize_sku(scraped.name, scraped.brand)

    product = session.query(Product).filter_by(sku_normalized=sku).first()
    if product is None:
        product = Product(
            id=str(uuid.uuid4()),
            name=scraped.name,
            brand=scraped.brand,
            category=scraped.category,
            sku_normalized=sku,
            image_url=scraped.image_url or None,
        )
        session.add(product)
        session.flush()
    else:
        product.name = scraped.name
        product.brand = scraped.brand
        product.category = scraped.category
        if scraped.image_url:
            product.image_url = scraped.image_url

    store_product = (
        session.query(StoreProduct)
        .filter_by(product_id=product.id, store=scraped.store)
        .first()
    )

    price_changed = True
    if store_product is None:
        store_product = StoreProduct(
            id=str(uuid.uuid4()),
            product_id=product.id,
            store=scraped.store,
            store_sku=scraped.store_sku or None,
            url=scraped.url or None,
            current_price=scraped.current_price,
            original_price=scraped.original_price,
            discount_percentage=scraped.discount_percentage,
            in_stock=scraped.in_stock,
            last_scraped_at=scraped.scraped_at,
        )
        session.add(store_product)
        session.flush()
    else:
        price_changed = (
            store_product.current_price != scraped.current_price
            or store_product.in_stock != scraped.in_stock
        )
        store_product.current_price = scraped.current_price
        store_product.original_price = scraped.original_price
        store_product.discount_percentage = scraped.discount_percentage
        store_product.in_stock = scraped.in_stock
        store_product.last_scraped_at = scraped.scraped_at
        if scraped.url:
            store_product.url = scraped.url
        if scraped.store_sku:
            store_product.store_sku = scraped.store_sku

    if price_changed and scraped.current_price > Decimal("0"):
        session.add(PriceHistory(
            id=str(uuid.uuid4()),
            store_product_id=store_product.id,
            price=scraped.current_price,
            original_price=scraped.original_price,
            in_stock=scraped.in_stock,
            scraped_at=scraped.scraped_at,
        ))

    return store_product


def log_scraping(
    session: Session,
    store: str,
    status: str,
    details: str = "",
    error: str = "",
) -> None:
    session.add(ScrapingLog(
        id=str(uuid.uuid4()),
        store=store,
        status=status,
        details=details or None,
        error=error or None,
    ))
