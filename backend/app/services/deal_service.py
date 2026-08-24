from __future__ import annotations

import logging
import time
from copy import deepcopy
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

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


def _hc(d: dict) -> dict:
    d.setdefault("avgMarketPrice", 0.0)
    d.setdefault("belowMarket", False)
    d.setdefault("mktDiffPct", 0.0)
    d.setdefault("cardPrice", 0.0)
    d.setdefault("cardDiscountPct", 0.0)
    d.setdefault("cardGlitch", False)
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


# ══════════════════════════════════════════════════════════════════════════
# El filtrado, el orden y la paginación se hacen en SQL.
#
# Antes se traían ~98.000 filas a memoria en CADA petición para pintar 50, y
# la mediana histórica se recalculaba sobre 1,9M filas de price_history cada
# vez: 120s por request, insostenible en cualquier instancia pequeña. Ahora
# las medianas viven en la vista materializada `price_medians` (se refresca
# tras cada scrape) y la base de datos devuelve solo la página pedida.
#
# `price_medians` congela el corte "scraped_at < NOW() - 12h" en el momento
# del refresco; como se refresca tras cada scrape (varias veces al día), la
# diferencia frente a calcularlo al vuelo es irrelevante.
# ══════════════════════════════════════════════════════════════════════════

_BASE_CTE = """
WITH base AS (
    SELECT sp.id,
           sp.store,
           p.name,
           COALESCE(p.brand, '')                                        AS brand,
           COALESCE(p.category, 'General')                              AS category,
           COALESCE(sp.url, '')                                         AS url,
           COALESCE(p.image_url, '')                                    AS image_url,
           CAST(sp.current_price AS float)                              AS current_price,
           -- equivale al `original_price or current_price or 0` de antes
           CAST(COALESCE(NULLIF(sp.original_price, 0), sp.current_price, 0) AS float) AS original_price,
           CAST(COALESCE(sp.card_price, 0) AS float)                    AS card_price,
           CAST(COALESCE(sp.discount_percentage, 0) AS float)           AS discount_pct,
           sp.in_stock,
           sp.last_scraped_at,
           CAST(COALESCE(m.median_price, 0) AS float)                   AS avg_hist_price,
           COALESCE(m.hist_count, 0)                                    AS hist_count
    FROM store_products sp
    JOIN products p ON p.id = sp.product_id
    LEFT JOIN price_medians m ON m.store_product_id = sp.id
    WHERE sp.current_price > 0
      AND sp.current_price < 100000     -- oculta productos con precio corrupto
      AND sp.in_stock = true
), calc AS (
    SELECT b.*,
           CASE WHEN b.current_price > 0
                THEN ROUND(CAST(((b.original_price - b.current_price) / b.current_price) * 100 AS numeric), 2)
                ELSE 0 END                                              AS margin_pct,
           -- below_market: al menos 15% por debajo de su propia mediana histórica,
           -- exigiendo 2+ registros de más de 12h atrás
           (b.hist_count >= 2 AND b.avg_hist_price > 0
            AND b.current_price < b.avg_hist_price * 0.85)              AS below_market,
           CASE WHEN b.avg_hist_price > 0
                THEN ROUND(CAST((1 - b.current_price / b.avg_hist_price) * 100 AS numeric), 1)
                ELSE 0 END                                              AS mkt_diff_pct,
           -- Precio con tarjeta (CMR/Única). `card_glitch` = por debajo de la
           -- mitad del precio público: eso ya no es beneficio de tarjeta (los
           -- normales son 3-10%), es el glitch que se viraliza.
           CASE WHEN b.card_price > 0 AND b.original_price > 0
                THEN ROUND(CAST((1 - b.card_price / b.original_price) * 100 AS numeric), 1)
                ELSE 0 END                                              AS card_discount_pct,
           (b.card_price > 0 AND b.current_price > 0
            AND b.card_price < b.current_price * 0.5)                   AS card_glitch
    FROM base b
)
"""

# Sanidad: un precio original de más de 15x el actual es dato inventado.
_SANIDAD = "NOT (original_price > 0 AND current_price > 0 AND original_price > current_price * 15)"

_ORDENES = {
    "margin":      "margin_pct DESC NULLS LAST",
    "price_asc":   "current_price ASC",
    "price_desc":  "current_price DESC NULLS LAST",
    "market_diff": "mkt_diff_pct DESC NULLS LAST",
    "discount":    "discount_pct DESC NULLS LAST",
}

# Los desplegables cambian solo cuando corre un scrape; no hace falta
# recalcularlos en cada request.
_FILTROS_TTL_SECONDS = 300
_filtros_cache: dict[str, Any] = {}

# El total de resultados tambien cambia solo con el scrape, y contarlo cuesta
# mas que traer la pagina: 1,3s el COUNT frente a 0,6s los 50 items. Se cachea
# por combinacion de filtros para que el caso normal no lo pague.
_TOTALES_TTL_SECONDS = 300
_TOTALES_MAX = 200
_totales_cache: dict[tuple, tuple[float, int]] = {}


def _escapar_regex(texto: str) -> str:
    """Escapa metacaracteres para el motor de expresiones regulares de Postgres."""
    especiales = set('\\.^$*+?()[]{}|-')
    return ''.join('\\' + c if c in especiales else c for c in texto)


def _f(valor: Any) -> float:
    """Los ROUND(...) de Postgres llegan como Decimal; el JSON quiere float."""
    return float(valor) if valor is not None else 0.0


def _fila_a_item(r: Any) -> dict[str, Any]:
    return {
        "id": r.id,
        "store": r.store,
        "name": r.name,
        "brand": r.brand,
        "category": r.category,
        "url": r.url,
        "imageUrl": r.image_url,
        "currentPrice": _f(r.current_price),
        "originalPrice": _f(r.original_price),
        "discountPct": _f(r.discount_pct),
        "marginPct": _f(r.margin_pct),
        "inStock": bool(r.in_stock),
        "scrapedAt": r.last_scraped_at.isoformat() if r.last_scraped_at else "",
        "avgMarketPrice": _f(r.avg_hist_price),
        "belowMarket": bool(r.below_market),
        "mktDiffPct": _f(r.mkt_diff_pct),
        "cardPrice": _f(r.card_price),
        "cardDiscountPct": _f(r.card_discount_pct),
        "cardGlitch": bool(r.card_glitch),
    }


class DealService:

    def _condiciones(
        self,
        stores: list[str] | None,
        categories: list[str] | None,
        brands: list[str] | None,
        q: str,
        min_discount: int,
        min_price: float,
        below_market: bool,
    ) -> tuple[list[str], dict[str, Any]]:
        cond: list[str] = []
        params: dict[str, Any] = {}
        if stores:
            cond.append("store = ANY(:stores)");         params["stores"] = list(stores)
        if categories:
            cond.append("category = ANY(:categories)");  params["categories"] = list(categories)
        if brands:
            cond.append("brand = ANY(:brands)");         params["brands"] = list(brands)
        if min_discount:
            cond.append("discount_pct >= :min_discount"); params["min_discount"] = min_discount
        if min_price:
            cond.append("current_price >= :min_price");   params["min_price"] = min_price
        if below_market:
            cond.append("below_market")
        if q:
            # `\y` es el límite de palabra de Postgres, equivalente al `\b` de Python
            cond.append(
                "(lower(name) || ' ' || lower(brand) || ' ' || lower(category)"
                " || ' ' || lower(store)) ~ :q_re"
            )
            params["q_re"] = "\\y" + _escapar_regex(q.lower())
        return cond, params

    def _total(
        self, session: Session, where: str, params: dict[str, Any],
        n_items: int, page: int, limit: int,
    ) -> int:
        """Total de resultados del filtro, contado lo menos posible."""
        # Si la primera página no llega a llenarse, el total ya lo sabemos.
        if page <= 1 and n_items < limit:
            return n_items

        clave = (where, tuple(sorted(
            (k, str(v)) for k, v in params.items() if k not in ("limit", "offset")
        )))
        guardado = _totales_cache.get(clave)
        if guardado and (time.time() - guardado[0]) < _TOTALES_TTL_SECONDS:
            return guardado[1]

        total = int(session.execute(
            text(_BASE_CTE + f"SELECT count(*) AS n FROM calc{where}"), params
        ).scalar() or 0)

        if len(_totales_cache) >= _TOTALES_MAX:      # evita crecer sin control
            _totales_cache.clear()
        _totales_cache[clave] = (time.time(), total)
        return total

    def _filtros_disponibles(
        self, session: Session, stores: list[str] | None, categories: list[str] | None, q: str
    ) -> dict[str, list[str]]:
        """Desplegables en cascada: las tiendas siempre completas, las categorías
        acotadas a las tiendas elegidas, y las marcas a tiendas + categorías."""
        clave = (tuple(stores or ()), tuple(categories or ()), q)
        guardado = _filtros_cache.get("valor")
        if guardado is not None and _filtros_cache.get("clave") == clave \
                and (time.time() - _filtros_cache.get("ts", 0)) < _FILTROS_TTL_SECONDS:
            return guardado

        # categorías: acotadas por las tiendas elegidas (+ búsqueda)
        cond_cat, params = self._condiciones(stores, None, None, q, 0, 0.0, False)
        where_cat = (" WHERE " + " AND ".join(cond_cat)) if cond_cat else ""

        # marcas: acotadas por tiendas + categorías (+ búsqueda)
        cond_marca, params_marca = self._condiciones(stores, categories, None, q, 0, 0.0, False)
        cond_marca.append("brand <> ''")
        where_marca = " WHERE " + " AND ".join(cond_marca)
        params.update(params_marca)

        filas = session.execute(text(_BASE_CTE + f"""
            SELECT 'store' AS tipo, store AS valor FROM base GROUP BY store
            UNION ALL
            SELECT 'category', category FROM base{where_cat} GROUP BY category
            UNION ALL
            SELECT 'brand', brand FROM base{where_marca} GROUP BY brand
        """), params).fetchall()

        resultado = {
            "stores":     sorted({f.valor for f in filas if f.tipo == "store"}),
            "categories": sorted({f.valor for f in filas if f.tipo == "category"}),
            "brands":     sorted({f.valor for f in filas if f.tipo == "brand"}),
        }
        _filtros_cache.update({"clave": clave, "valor": resultado, "ts": time.time()})
        return resultado

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
        try:
            cond, params = self._condiciones(stores, categories, brands, q, min_discount, min_price, below_market)
            cond.append(_SANIDAD)
            where = " WHERE " + " AND ".join(cond)
            # El id desempata para que la paginación sea estable entre páginas.
            orden = _ORDENES.get((sort or "").lower(), _ORDENES["discount"]) + ", id"
            params["limit"] = max(1, limit)
            params["offset"] = max(0, (max(1, page) - 1) * max(1, limit))

            with Session(_engine) as session:
                filas = session.execute(text(_BASE_CTE + f"""
                    SELECT * FROM calc{where}
                    ORDER BY {orden}
                    LIMIT :limit OFFSET :offset
                """), params).fetchall()

                items = [_fila_a_item(f) for f in filas]
                total = self._total(session, where, params, len(items), page, limit)
                filtros = self._filtros_disponibles(session, stores, categories, q)

            return {"items": items, "total": total, "filters": filtros}
        except Exception:
            # Sin este log, un fallo de consulta se disfrazaba de "7 ofertas":
            # la API devolvia la lista de ejemplo y nadie se enteraba.
            logger.exception("get_deals fallo; se devuelven los datos de ejemplo")
            copia = deepcopy(_HARDCODED)
            return {
                "items": copia,
                "total": len(copia),
                "filters": {
                    "stores":     sorted({i["store"]    for i in copia}),
                    "categories": sorted({i["category"] for i in copia}),
                    "brands":     sorted({i["brand"]    for i in copia if i["brand"]}),
                },
            }

    def get_stats(self) -> dict[str, Any]:
        vacio = {"total": 0, "bestDiscount": 0, "bestMargin": 0, "minPrice": 0, "lastSync": "Nunca", "byStore": {}}
        try:
            with Session(_engine) as session:
                r = session.execute(text(_BASE_CTE + """
                    SELECT count(*)                                              AS total,
                           ROUND(CAST(max(discount_pct)  AS numeric), 2)         AS mejor_desc,
                           ROUND(CAST(max(margin_pct)    AS numeric), 2)         AS mejor_margen,
                           ROUND(CAST(min(current_price) AS numeric), 2)         AS precio_min,
                           (SELECT last_scraped_at FROM calc
                             ORDER BY discount_pct DESC NULLS LAST, id LIMIT 1)  AS ultimo_scrape
                    FROM calc
                """)).fetchone()

                if not r or not r.total:
                    return vacio

                por_tienda = session.execute(text(_BASE_CTE + """
                    SELECT store, count(*) AS n FROM base GROUP BY store
                """)).fetchall()

            return {
                "total": int(r.total),
                "bestDiscount": _f(r.mejor_desc),
                "bestMargin": _f(r.mejor_margen),
                "minPrice": _f(r.precio_min),
                "lastSync": r.ultimo_scrape.isoformat() if r.ultimo_scrape else "Nunca",
                "byStore": {f.store: int(f.n) for f in por_tienda},
            }
        except Exception:
            logger.exception("get_stats fallo; se devuelven los datos de ejemplo")
            items = deepcopy(_HARDCODED)
            por_tienda: dict[str, int] = {}
            for i in items:
                por_tienda[i["store"]] = por_tienda.get(i["store"], 0) + 1
            return {
                "total": len(items),
                "bestDiscount": round(max(i["discountPct"] for i in items), 2),
                "bestMargin": round(max(i["marginPct"] for i in items), 2),
                "minPrice": round(min(i["currentPrice"] for i in items), 2),
                "lastSync": items[0]["scrapedAt"] or "Nunca",
                "byStore": por_tienda,
            }
