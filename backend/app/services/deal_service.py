from __future__ import annotations

import re
import time
from copy import deepcopy
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import get_settings

settings = get_settings()

_sync_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
# statement_timeout=600s: el default de Supabase (2 min) cancela las escrituras
# masivas de tiendas grandes (Falabella tras arreglar la paginación: ~11k filas
# en el bulk-update de `products` + el UPDATE de in_stock con un array grande).
# 10 min da margen holgado; las lecturas son rápidas y no se ven afectadas.
_engine = create_engine(
    _sync_url,
    pool_pre_ping=True,
    pool_recycle=1800,                          # recicla conexiones antes de que el pooler de Supabase las corte (evita SSL EOF)
    executemany_mode="values_plus_batch",       # bulk insert/update en pocas sentencias, no miles de round-trips
)

# Caché en memoria de los items. La data solo cambia cuando corre un scrape
# (pocas veces al día), así que un TTL corto evita re-consultar ~11k filas en
# cada request (get_deals llama _load_items dos veces por llamada).
_CACHE_TTL_SECONDS = 180
_items_cache: dict[str, Any] = {"ts": 0.0, "items": None}

def _hc(d: dict) -> dict:
    d.setdefault("avgMarketPrice", 0.0)
    d.setdefault("belowMarket", False)
    d.setdefault("mktDiffPct", 0.0)
    return d

_HARDCODED: list[dict[str, Any]] = [
    _hc({"id": "deal-001", "store": "falabella", "name": "Nike Air Max 90", "brand": "Nike", "category": "Calzado", "url": "https://www.falabella.com.pe", "imageUrl": "", "currentPrice": 179.9, "originalPrice": 299.9, "discountPct": 40.0, "marginPct": 66.7, "inStock": True, "scrapedAt": "2026-06-12T20:00:00Z"}),
    _hc({"id": "deal-002", "store": "ripley", "name": "Tramontina Starter 10 piezas", "brand": "Tramontina", "category": "Hogar", "url": "https://simple.ripley.com.pe", "imageUrl": "", "currentPrice": 129.0, "originalPrice": 219.0, "discountPct": 41.1, "marginPct": 69.8, "inStock": True, "scrapedAt": "2026-06-12T19:50:00Z"}),
    _hc({"id": "deal-003", "store": "plazavea", "name": "Samsung Galaxy A24", "brand": "Samsung", "category": "Celulares", "url": "https://www.plazavea.com.pe", "imageUrl": "", "currentPrice": 799.0, "originalPrice": 1099.0, "discountPct": 27.3, "marginPct": 37.5, "inStock": True, "scrapedAt": "2026-06-12T19:40:00Z"}),
    _hc({"id": "deal-004", "store": "oechsle", "name": "Sony WH-1000XM5", "brand": "Sony", "category": "Audio", "url": "https://www.oechsle.pe", "imageUrl": "", "currentPrice": 1499.0, "originalPrice": 2099.0, "discountPct": 28.6, "marginPct": 40.0, "inStock": False, "scrapedAt": "2026-06-12T19:30:00Z"}),
    _hc({"id": "deal-005", "store": "promart", "name": "Laptop Lenovo IdeaPad 3", "brand": "Lenovo", "category": "Tecnología", "url": "https://www.promart.pe", "imageUrl": "", "currentPrice": 1399.0, "originalPrice": 1999.0, "discountPct": 30.0, "marginPct": 42.9, "inStock": True, "scrapedAt": "2026-06-12T19:25:00Z"}),
    _hc({"id": "deal-006", "store": "tottus", "name": "Cocina eléctrica Oster", "brand": "Oster", "category": "Hogar", "url": "https://www.tottus.com.pe", "imageUrl": "", "currentPrice": 189.9, "originalPrice": 289.9, "discountPct": 34.5, "marginPct": 52.7, "inStock": True, "scrapedAt": "2026-06-12T19:15:00Z"}),
    _hc({"id": "deal-007", "store": "hiraoka", "name": "Smart TV TCL 50", "brand": "TCL", "category": "Electrónica", "url": "https://www.hiraoka.com.pe", "imageUrl": "", "currentPrice": 999.0, "originalPrice": 1499.0, "discountPct": 33.4, "marginPct": 50.2, "inStock": True, "scrapedAt": "2026-06-12T19:10:00Z"}),
]


class DealService:
    def _load_items(self) -> list[dict[str, Any]]:
        now = time.time()
        cached = _items_cache["items"]
        if cached is not None and (now - _items_cache["ts"]) < _CACHE_TTL_SECONDS:
            return cached
        try:
            with Session(_engine) as session:
                rows = session.execute(text("""
                    WITH hist AS (
                        SELECT
                            store_product_id,
                            -- MEDIANA (no promedio): un solo registro corrupto que pase el
                            -- filtro <100k (p.ej. S/99.349 en unos audífonos) disparaba el
                            -- AVG a S/20.149 y mostraba "PROM. HISTÓRICO" absurdo + "98% bajo
                            -- mercado" falso. La mediana es inmune a esos outliers.
                            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price) AS avg_hist_price,
                            COUNT(*)    AS hist_count
                        FROM price_history
                        WHERE price > 0
                          AND price < 100000            -- excluye precios basura (parsing corrupto)
                          AND scraped_at < NOW() - INTERVAL '12 hours'
                        GROUP BY store_product_id
                    )
                    SELECT
                        sp.id,
                        sp.store,
                        p.name,
                        COALESCE(p.brand, '')              AS brand,
                        COALESCE(p.category, 'General')    AS category,
                        COALESCE(sp.url, '')               AS url,
                        COALESCE(p.image_url, '')          AS image_url,
                        CAST(sp.current_price  AS float)   AS current_price,
                        CAST(sp.original_price AS float)   AS original_price,
                        CAST(sp.discount_percentage AS float) AS discount_pct,
                        sp.in_stock,
                        sp.last_scraped_at,
                        CAST(COALESCE(h.avg_hist_price, 0) AS float) AS avg_hist_price,
                        COALESCE(h.hist_count, 0)                    AS hist_count
                    FROM store_products sp
                    JOIN products p ON p.id = sp.product_id
                    LEFT JOIN hist h ON h.store_product_id = sp.id
                    WHERE sp.current_price > 0
                      AND sp.current_price < 100000     -- oculta productos con precio corrupto
                      AND sp.in_stock = true
                    ORDER BY sp.discount_percentage DESC NULLS LAST
                    -- Con Shopstar (24.8k in_stock) el universo pasó de ~34k a ~59k y el
                    -- LIMIT 50000 recortaba ~9.2k productos en silencio (los de menor
                    -- descuento, por el ORDER BY). Se sube con margen para crecer.
                    LIMIT 120000
                """)).fetchall()

                if not rows:
                    return deepcopy(_HARDCODED)

                items = []
                for r in rows:
                    orig = r.original_price or r.current_price or 0
                    margin = 0.0
                    current = float(r.current_price or 0)
                    avg_hist = float(r.avg_hist_price or 0)
                    hist_count = int(r.hist_count or 0)
                    if current > 0:
                        margin = round(((orig - current) / current) * 100, 2)
                    # below_market: precio actual al menos 15% menor al promedio histórico propio
                    # requiere al menos 2 registros históricos de más de 12h atrás
                    below_market = (
                        hist_count >= 2
                        and avg_hist > 0
                        and current < avg_hist * 0.85
                    )
                    mkt_diff_pct = round((1 - current / avg_hist) * 100, 1) if avg_hist > 0 else 0.0
                    avg_mkt = avg_hist
                    scraped_at = r.last_scraped_at.isoformat() if r.last_scraped_at else ""
                    items.append({
                        "id": r.id,
                        "store": r.store,
                        "name": r.name,
                        "brand": r.brand,
                        "category": r.category,
                        "url": r.url,
                        "imageUrl": r.image_url,
                        "currentPrice": current,
                        "originalPrice": float(orig),
                        "discountPct": float(r.discount_pct or 0),
                        "marginPct": margin,
                        "inStock": bool(r.in_stock),
                        "scrapedAt": scraped_at,
                        "avgMarketPrice": avg_mkt,
                        "belowMarket": below_market,
                        "mktDiffPct": mkt_diff_pct,
                    })
                _items_cache["items"] = items
                _items_cache["ts"] = now
                return items
        except Exception:
            return deepcopy(_HARDCODED)

    def get_deals(
        self,
        stores: list[str] | None = None,
        categories: list[str] | None = None,
        brands: list[str] | None = None,
        sort: str = "discount",
        q: str = "",
        min_discount: int = 0,
        min_price: float = 0.0,
        page: int = 1,
        limit: int = 50,
        below_market: bool = False,
    ) -> dict[str, Any]:
        items = self._load_items()

        filtered = []
        for item in items:
            if stores and item["store"] not in stores:
                continue
            if categories and item["category"] not in categories:
                continue
            if brands and item["brand"] not in brands:
                continue
            if min_discount and item["discountPct"] < min_discount:
                continue
            if min_price and item["currentPrice"] < min_price:
                continue
            # Sanidad: precio original no puede ser más de 15x el precio actual (datos inventados)
            if item["originalPrice"] > 0 and item["currentPrice"] > 0:
                if item["originalPrice"] > item["currentPrice"] * 15:
                    continue
            if below_market and not item.get("belowMarket"):
                continue
            if q:
                haystack = " ".join([item["name"], item["brand"], item["category"], item["store"]]).lower()
                pattern = r'\b' + re.escape(q.lower())
                if not re.search(pattern, haystack):
                    continue
            filtered.append(item)

        filtered = self._sort(filtered, sort)
        total = len(filtered)
        start = (page - 1) * limit
        page_items = filtered[start: start + limit]

        all_items = self._load_items()

        # Filtros en cascada:
        # stores   → siempre todos (sin filtrar)
        # categories → solo las disponibles en las tiendas seleccionadas (+ query)
        # brands   → solo las disponibles en tiendas + categoría seleccionados (+ query)
        def _matches_q(item: dict) -> bool:
            if not q:
                return True
            haystack = " ".join([item["name"], item["brand"], item["category"], item["store"]]).lower()
            return bool(re.search(r'\b' + re.escape(q.lower()), haystack))

        by_store = [i for i in all_items if (not stores or i["store"] in stores) and _matches_q(i)]
        by_store_and_cat = [i for i in by_store if not categories or i["category"] in categories]

        return {
            "items": page_items,
            "total": total,
            "filters": {
                "stores":     sorted({i["store"]    for i in all_items}),
                "categories": sorted({i["category"] for i in by_store}),
                "brands":     sorted({i["brand"]    for i in by_store_and_cat if i["brand"]}),
            },
        }

    def get_stats(self) -> dict[str, Any]:
        items = self._sort(self._load_items(), "discount")
        if not items:
            return {"total": 0, "bestDiscount": 0, "bestMargin": 0, "minPrice": 0, "lastSync": "Nunca", "byStore": {}}

        by_store: dict[str, int] = {}
        for item in items:
            by_store[item["store"]] = by_store.get(item["store"], 0) + 1

        return {
            "total": len(items),
            "bestDiscount": round(items[0]["discountPct"], 2),
            "bestMargin": round(max(i["marginPct"] for i in items), 2),
            "minPrice": round(min(i["currentPrice"] for i in items), 2),
            "lastSync": items[0]["scrapedAt"] or "Nunca",
            "byStore": by_store,
        }

    def _sort(self, items: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
        key = sort.lower()
        if key == "margin":
            return sorted(items, key=lambda i: i["marginPct"], reverse=True)
        if key == "price_asc":
            return sorted(items, key=lambda i: i["currentPrice"])
        if key == "price_desc":
            return sorted(items, key=lambda i: i["currentPrice"], reverse=True)
        if key == "market_diff":
            return sorted(items, key=lambda i: i.get("mktDiffPct", 0), reverse=True)
        return sorted(items, key=lambda i: i["discountPct"], reverse=True)
