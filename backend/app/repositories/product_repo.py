from __future__ import annotations

import re
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PriceHistory, Product, ScrapingLog, StoreProduct
from app.scrapers.base import ScrapedProduct


def _normalize_sku(name: str, brand: str) -> str:
    base = f"{brand.strip()}-{name.strip()}".lower()
    return re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:100]


def bulk_upsert_store(session: Session, store: str, scraped: list[ScrapedProduct]) -> tuple[int, int, list[str]]:
    """Upsert masivo de una tienda: precarga los mapas existentes en memoria
    (2 queries) y escribe todo en lote (bulk insert/update). Reemplaza el
    patrón fila-por-fila, que sobre una BD remota (Supabase) hacía miles de
    round-trips y tardaba horas. Devuelve (saved, errors, seen_ids)."""
    # 1) Precargar en memoria (2 queries en vez de 2 por producto)
    existing_prod: dict[str, dict] = {
        sku: {"id": pid, "name": name, "brand": brand, "category": category, "image_url": image_url}
        for sku, pid, name, brand, category, image_url in session.execute(
            select(
                Product.sku_normalized, Product.id, Product.name,
                Product.brand, Product.category, Product.image_url,
            )
        ).all()
    }
    existing_sp: dict[str, dict] = {
        pid: {"id": spid, "price": price, "stock": stock}
        for pid, spid, price, stock in session.execute(
            select(
                StoreProduct.product_id, StoreProduct.id,
                StoreProduct.current_price, StoreProduct.in_stock,
            ).where(StoreProduct.store == store)
        ).all()
    }

    new_products: list[dict] = []
    product_updates: list[dict] = []
    new_sps: list[dict] = []
    sp_updates: list[dict] = []
    price_rows: list[dict] = []
    seen_ids: list[str] = []
    saved = 0
    errors = 0

    for s in scraped:
        try:
            sku = _normalize_sku(s.name, s.brand)
            prod = existing_prod.get(sku)
            if prod is None:
                pid = str(uuid.uuid4())
                existing_prod[sku] = {
                    "id": pid, "name": s.name, "brand": s.brand,
                    "category": s.category, "image_url": s.image_url or None,
                }
                new_products.append({
                    "id": pid, "name": s.name, "brand": s.brand,
                    "category": s.category, "sku_normalized": sku,
                    "image_url": s.image_url or None,
                })
            else:
                pid = prod["id"]
                # Refrescar campos del Product si cambiaron (la imagen solo si el
                # scrape trae una). Igual que el upsert fila-por-fila original.
                new_image = s.image_url or prod["image_url"]
                if (prod["name"] != s.name or prod["brand"] != s.brand
                        or prod["category"] != s.category or prod["image_url"] != new_image):
                    product_updates.append({
                        "id": pid, "name": s.name, "brand": s.brand,
                        "category": s.category, "image_url": new_image,
                    })
                    prod.update(name=s.name, brand=s.brand, category=s.category, image_url=new_image)

            row = existing_sp.get(pid)
            if row is None:
                spid = str(uuid.uuid4())
                new_sps.append({
                    "id": spid, "product_id": pid, "store": s.store,
                    "store_sku": s.store_sku or None, "url": s.url or None,
                    "current_price": s.current_price, "original_price": s.original_price,
                    "discount_percentage": s.discount_percentage,
                    "in_stock": s.in_stock, "last_scraped_at": s.scraped_at,
                })
                existing_sp[pid] = {"id": spid, "price": s.current_price, "stock": s.in_stock}
                price_changed = True
            else:
                spid = row["id"]
                price_changed = (row["price"] != s.current_price or row["stock"] != s.in_stock)
                sp_updates.append({
                    "id": spid,
                    "current_price": s.current_price, "original_price": s.original_price,
                    "discount_percentage": s.discount_percentage,
                    "in_stock": s.in_stock, "last_scraped_at": s.scraped_at,
                    "url": s.url or None, "store_sku": s.store_sku or None,
                })
                row["price"] = s.current_price
                row["stock"] = s.in_stock

            seen_ids.append(spid)
            if price_changed and s.current_price and s.current_price > Decimal("0"):
                price_rows.append({
                    "id": str(uuid.uuid4()), "store_product_id": spid,
                    "price": s.current_price, "original_price": s.original_price,
                    "in_stock": s.in_stock, "scraped_at": s.scraped_at,
                })
            saved += 1
        except Exception:
            errors += 1

    # 2) Escrituras masivas (pocas queries). Orden: productos -> store_products
    #    (flush para FK) -> updates -> price_history.
    if new_products:
        session.bulk_insert_mappings(Product, new_products)
    if product_updates:
        session.bulk_update_mappings(Product, product_updates)
    if new_sps:
        session.bulk_insert_mappings(StoreProduct, new_sps)
    session.flush()
    if sp_updates:
        session.bulk_update_mappings(StoreProduct, sp_updates)
    if price_rows:
        session.bulk_insert_mappings(PriceHistory, price_rows)

    return saved, errors, seen_ids


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
