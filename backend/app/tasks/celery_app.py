from __future__ import annotations

import asyncio
import traceback

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init
from celery.utils.log import get_task_logger
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings

settings = get_settings()
logger = get_task_logger(__name__)

app = Celery("pricehunter", broker=settings.redis_url, backend=settings.redis_url)
app.conf.task_serializer = "json"
app.conf.result_serializer = "json"
app.conf.accept_content = ["json"]
app.conf.timezone = "America/Lima"
app.conf.enable_utc = True
app.conf.beat_schedule = {
    "scrape-00:30am": {"task": "scrape_all_stores", "schedule": crontab(hour=0,  minute=30)},
    "scrape-01:30am": {"task": "scrape_all_stores", "schedule": crontab(hour=1,  minute=30)},
    "scrape-03:00am": {"task": "scrape_all_stores", "schedule": crontab(hour=3,  minute=0)},
    "scrape-06:00am": {"task": "scrape_all_stores", "schedule": crontab(hour=6,  minute=0)},
    "scrape-08:00am": {"task": "scrape_all_stores", "schedule": crontab(hour=8,  minute=0)},
    "scrape-10:00am": {"task": "scrape_all_stores", "schedule": crontab(hour=10, minute=0)},
    "scrape-12:00pm": {"task": "scrape_all_stores", "schedule": crontab(hour=12, minute=0)},
    "scrape-03:00pm": {"task": "scrape_all_stores", "schedule": crontab(hour=15, minute=0)},
    "scrape-06:00pm": {"task": "scrape_all_stores", "schedule": crontab(hour=18, minute=0)},
    "scrape-08:00pm": {"task": "scrape_all_stores", "schedule": crontab(hour=20, minute=0)},
    "scrape-10:00pm": {"task": "scrape_all_stores", "schedule": crontab(hour=22, minute=0)},
    # Publicar top 5 gangas en Telegram a las 8am, 12pm y 8pm
    "gangas-08:00am": {"task": "publish_top_deals",      "schedule": crontab(hour=8,  minute=0)},
    "gangas-12:00pm": {"task": "publish_top_deals",      "schedule": crontab(hour=12, minute=5)},
    "gangas-08:00pm": {"task": "publish_top_deals",      "schedule": crontab(hour=20, minute=5)},
    # Generar imagen TikTok y enviar al admin a las 7am para subir manualmente
    "tiktok-07:00am": {"task": "generate_tiktok_content", "schedule": crontab(hour=7, minute=0)},
}

# Sync engine for Celery tasks (psycopg2, not asyncpg)
_sync_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
# pool_recycle evita que el pooler de Supabase corte conexiones idle largas.
# executemany_mode acelera las escrituras masivas (execute_values/execute_batch
# de psycopg2), clave con la latencia remota de Supabase.
_engine = create_engine(
    _sync_url, pool_pre_ping=True, pool_recycle=1800,
    executemany_mode="values_plus_batch",
)
# Nota: el statement_timeout (2 min por defecto en Supabase) se amplía por
# transacción con `SET LOCAL` dentro de bulk_upsert_store; el pooler ignora el
# `options` de connect_args, por eso no se fija aquí.


@worker_process_init.connect
def _dispose_engine_on_fork(**_kwargs) -> None:
    """Celery prefork: cada worker hijo hereda el pool del padre. Las conexiones
    (sobre todo SSL, como las de Supabase) NO son fork-safe y se corrompen al
    compartirse. Descartamos el pool heredado para que cada proceso abra las
    suyas propias."""
    _engine.dispose()


@app.task(name="scrape_all_stores")
def scrape_all_stores() -> dict:
    """Singleton: impide que dos scrapes corran a la vez. Antes, con el beat
    (muchos horarios) + concurrency=4, se solapaban y hacían DEADLOCK al escribir
    los mismos productos. Si ya hay uno corriendo, se omite este disparo."""
    import redis as _redis
    _lock = _redis.from_url(settings.redis_url).lock(
        "lock:scrape_all_stores", timeout=7200, blocking=False
    )
    if not _lock.acquire(blocking=False):
        logger.warning("scrape_all_stores ya en ejecución; se omite este disparo")
        return {"skipped": "already_running"}
    try:
        return _run_scrape_all_stores()
    finally:
        try:
            _lock.release()
        except Exception:
            pass


def _push_log(r, modulo: str, mensaje: str, severidad: str = "info") -> None:
    import json
    from datetime import datetime, timezone
    entry = json.dumps({
        "fecha": datetime.now(timezone.utc).strftime("%d/%m %H:%M"),
        "modulo": modulo,
        "tipo": severidad.upper(),
        "mensaje": mensaje,
        "severidad": severidad,
    })
    r.lpush("system:logs", entry)
    r.ltrim("system:logs", 0, 199)


def _run_scrape_all_stores() -> dict:
    import redis as _redis
    from app.scrapers.falabella_scraper import FalabellaScraper
    from app.scrapers.ripley_scraper import RipleyScraper
    from app.scrapers.plazavea_scraper import PlazaVeaScraper
    from app.scrapers.oechsle_scraper import OechsleScraper
    from app.scrapers.estilos_scraper import EstilosScraper
    from app.scrapers.sodimac_scraper import SodimacScraper
    from app.scrapers.tottus_scraper import TottusScraper
    from app.scrapers.mercadolibre_scraper import MercadoLibreScraper
    from app.scrapers.shopstar_scraper import ShopstarScraper
    from app.repositories.product_repo import bulk_upsert_store, log_scraping

    r_log = _redis.from_url(settings.redis_url)
    scrapers = [FalabellaScraper(), RipleyScraper(), PlazaVeaScraper(), OechsleScraper(), EstilosScraper(), SodimacScraper(), TottusScraper(), MercadoLibreScraper(), ShopstarScraper()]
    results: dict[str, object] = {}

    _push_log(r_log, "CeleryBeat", f"Scrape iniciado ({len(scrapers)} tiendas)", "info")

    for scraper in scrapers:
        store = getattr(scraper, "store", type(scraper).__name__)
        store_label = store.capitalize() + "Scraper"
        try:
            from sqlalchemy import text as sql_text
            products = asyncio.run(scraper.get_category())
            with Session(_engine) as session:
                saved, errors, seen_ids = bulk_upsert_store(session, store, products)
                # Only after a successful scrape: mark unseen products as out-of-stock.
                # This avoids the "temporary disappearance" window of the old pre-mark approach.
                if seen_ids:
                    session.execute(
                        sql_text("""
                            UPDATE store_products
                            SET in_stock = false
                            WHERE store = :store
                              AND id != ALL(:seen_ids)
                              AND in_stock = true
                        """),
                        {"store": store, "seen_ids": seen_ids},
                    )
                log_scraping(session, store, "success", details=f"saved={saved} errors={errors}")
                session.commit()
            results[store] = {"status": "ok", "saved": saved, "errors": errors}
            sev = "warning" if saved < 300 else "info"
            suffix = " (bajo promedio)" if saved < 300 else ""
            _push_log(r_log, store_label, f"{saved:,} productos guardados{suffix}", sev)
        except Exception as exc:
            with Session(_engine) as session:
                log_scraping(session, store, "error", error=str(exc))
                session.commit()
            results[store] = {"status": "error", "error": str(exc), "trace": traceback.format_exc()[-500:]}
            _push_log(r_log, store_label, f"Error: {str(exc)[:100]}", "error")

    # Notificar nuevas alertas por Telegram al finalizar todos los scrapers
    try:
        alerts_sent = _notify_new_alerts(r_log=r_log)
        if alerts_sent:
            channels = sum(1 for c in [settings.telegram_channel_dev, settings.telegram_channel_prd] if c)
            _push_log(r_log, "TelegramNotifier", f"{alerts_sent} alerta(s) enviada(s) a {channels} canal(es)", "info")
        else:
            _push_log(r_log, "TelegramNotifier", "Sin nuevas alertas calificadas", "info")
    except Exception:
        pass

    next_slots = [
        (0, 30), (1, 30), (3, 0), (6, 0), (8, 0),
        (10, 0), (12, 0), (15, 0), (18, 0), (20, 0), (22, 0),
    ]
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    now_lima = datetime.now(ZoneInfo("America/Lima"))
    next_run = "—"
    for h, m in next_slots:
        candidate = now_lima.replace(hour=h, minute=m, second=0, microsecond=0)
        if candidate <= now_lima:
            candidate += timedelta(days=1)
        next_run = candidate.strftime("%H:%M")
        break
    _push_log(r_log, "CeleryBeat", f"Próximo scrape programado: {next_run}", "info")

    return results


def _notify_new_alerts(r_log=None) -> int:
    from app.services.telegram_notifier import notify_new_alerts
    from app.core.config import get_settings
    from sqlalchemy import text
    import redis as redis_lib

    settings = get_settings()
    if not settings.telegram_bot_token:
        return 0

    r = redis_lib.from_url(settings.redis_url)

    with Session(_engine) as session:
        rows = session.execute(text("""
            WITH hist AS (
                SELECT store_product_id,
                       AVG(price) AS avg_hist_price,
                       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price) AS med_hist_price,
                       COUNT(*)   AS hist_count
                FROM price_history
                WHERE price > 0
                  AND price < 100000            -- excluye precios basura (parsing corrupto)
                  AND scraped_at < NOW() - INTERVAL '12 hours'
                GROUP BY store_product_id
            ),
            market AS (
                SELECT p2.sku_normalized,
                       AVG(sp2.current_price) AS avg_market_price,
                       COUNT(DISTINCT sp2.store) AS store_count
                FROM store_products sp2
                JOIN products p2 ON p2.id = sp2.product_id
                WHERE sp2.in_stock = true
                  AND sp2.current_price > 0
                  AND p2.sku_normalized IS NOT NULL
                GROUP BY p2.sku_normalized
            ),
            candidates AS (
                -- Un row por SKU: la mejor oferta disponible, con filtros de calidad
                SELECT DISTINCT ON (COALESCE(p.sku_normalized, sp.id))
                    sp.id, sp.store, p.name, sp.url,
                    COALESCE(p.image_url, '') AS image_url,
                    sp.current_price, sp.original_price,
                    sp.discount_percentage, p.sku_normalized
                FROM store_products sp
                JOIN products p ON p.id = sp.product_id
                LEFT JOIN hist hc ON hc.store_product_id = sp.id
                WHERE sp.in_stock = true
                  AND sp.current_price > 0
                  AND sp.original_price > sp.current_price        -- precio original SIEMPRE mayor al actual
                  AND sp.current_price >= 50                       -- mínimo S/50 precio actual
                  AND sp.original_price >= 100                     -- mínimo S/100 precio original
                  AND (sp.original_price - sp.current_price) >= 100  -- ahorro real >= S/100
                  AND sp.original_price < 100000                  -- guard absoluto anti-basura (parsing corrupto = millones)
                  AND (
                        sp.original_price < sp.current_price * 10  -- caso normal (hasta ~90% off)
                        OR (                                       -- ERROR DE PRECIO: permite >10x SOLO si la MEDIANA histórica lo confirma
                            hc.hist_count >= 3 AND hc.med_hist_price > 0
                            AND sp.current_price < hc.med_hist_price * 0.30
                        )
                  )
                  AND (sp.original_price - sp.current_price) / sp.original_price >= 0.10  -- >=10% real
                ORDER BY COALESCE(p.sku_normalized, sp.id), sp.current_price ASC
            )
            SELECT c.id, c.store, c.name, c.url,
                   c.image_url,
                   CAST(c.current_price AS float)                          AS current_price,
                   CAST(c.original_price AS float)                         AS original_price,
                   CAST(COALESCE(
                       NULLIF(h.avg_hist_price, 0),
                       m.avg_market_price,
                       c.original_price, 0
                   ) AS float)                                             AS avg_hist_price,
                   COALESCE(h.hist_count, 0)                              AS hist_count,
                   CAST(COALESCE(m.avg_market_price, 0) AS float)         AS avg_market_price,
                   COALESCE(m.store_count, 0)                             AS store_count,
                   CAST((c.original_price - c.current_price) / c.original_price * 100 AS float) AS real_discount_pct,
                   -- ERROR DE PRECIO (glitch): >=70% bajo su MEDIANA histórica, con historia
                   -- confiable (>=3 registros). Mediana (no promedio) = inmune a outliers de
                   -- parsing; y no usa original_price = inmune a original corrupto.
                   CASE WHEN h.hist_count >= 3 AND h.med_hist_price > 0
                             AND c.current_price < h.med_hist_price * 0.30
                        THEN true ELSE false END                          AS is_price_error
            FROM candidates c
            LEFT JOIN hist h ON h.store_product_id = c.id
            LEFT JOIN market m ON m.sku_normalized = c.sku_normalized
            WHERE (
                -- Alerta histórica: >=15% bajo el promedio histórico real
                (h.hist_count >= 1
                 AND h.avg_hist_price > 0
                 AND c.current_price < h.avg_hist_price * 0.85)
                OR
                -- Alerta inmediata: descuento REAL >= 40% (calculado, no campo almacenado)
                ((c.original_price - c.current_price) / c.original_price >= 0.40)
                OR
                -- Alerta de mercado: >=15% bajo el promedio cross-tienda (>=2 tiendas)
                (m.store_count >= 2
                 AND m.avg_market_price > 0
                 AND c.current_price < m.avg_market_price * 0.85)
            )
            ORDER BY (
                ((c.original_price - c.current_price) / c.original_price * 100) *
                LEAST(CAST(c.original_price - c.current_price AS float), 3000)
            ) DESC
            LIMIT 100
        """)).fetchall()

    new_alerts = []
    for r_row in rows:
        key = f"tg_notified:{r_row.id}"
        if r.exists(key):
            continue

        # Validación Python: doble chequeo de que hay descuento real
        real_disc = getattr(r_row, "real_discount_pct", 0) or 0
        if real_disc < 10:          # menos de 10% descuento real → ignorar
            continue
        if r_row.current_price <= 0:
            continue

        ref_price = r_row.avg_hist_price if r_row.avg_hist_price else 0
        diff = round((1 - r_row.current_price / ref_price) * 100, 1) if ref_price else 0

        # Si el precio de referencia no supera al precio actual, no es una alerta válida
        if ref_price > 0 and ref_price <= r_row.current_price:
            diff = round(real_disc, 1)      # usa el descuento original como referencia
            ref_price = getattr(r_row, "original_price", r_row.current_price)

        new_alerts.append({
            "id":            r_row.id,
            "name":          r_row.name,
            "store":         r_row.store,
            "imageUrl":      r_row.image_url or "",
            "currentPrice":  r_row.current_price,
            "avgMarketPrice": ref_price,
            "mktDiffPct":    diff,
            "url":           r_row.url or "",
            "priceError":    bool(getattr(r_row, "is_price_error", False)),
            "_key":          key,
        })

    # Los errores de precio (glitches) van PRIMERO: son el contenido más viral.
    new_alerts.sort(key=lambda a: not a["priceError"])

    channels = [c for c in [settings.telegram_channel_dev, settings.telegram_channel_prd] if c]
    sent_count = 0
    for alert in new_alerts:
        ok_any = False
        for channel in channels:
            if notify_new_alerts([alert], channel_id=channel):
                ok_any = True
        # Marcar en Redis SOLO si se envió realmente — evita silenciar deals no enviados
        if ok_any:
            r.setex(alert["_key"], 86400, "1")
            sent_count += 1
    return sent_count


@app.task(name="publish_top_deals")
def publish_top_deals(limit: int = 5, min_discount: float = 40.0) -> dict:
    """Publica los mejores deals del momento en el canal de Telegram."""
    from app.notifications.telegram import send_deals_batch, notify_admin
    from sqlalchemy import text

    with Session(_engine) as session:
        rows = session.execute(text("""
            SELECT sp.id, sp.store, p.name, p.brand, p.category,
                   COALESCE(p.image_url, '')          AS image_url,
                   CAST(sp.current_price  AS float)   AS current_price,
                   CAST(sp.original_price AS float)   AS original_price,
                   CAST(sp.discount_percentage AS float) AS discount_pct,
                   sp.url
            FROM store_products sp
            JOIN products p ON p.id = sp.product_id
            WHERE sp.in_stock = true
              AND sp.original_price > sp.current_price
              AND (sp.original_price - sp.current_price) / sp.original_price >= :min_discount / 100.0
              AND sp.current_price > 0
              AND sp.original_price > 0
              AND (sp.original_price - sp.current_price) >= 50
            ORDER BY (sp.original_price - sp.current_price) / sp.original_price DESC
            LIMIT :limit
        """), {"min_discount": min_discount, "limit": limit}).fetchall()

    deals = [
        {
            "name":          r.name,
            "store":         r.store,
            "brand":         r.brand or "",
            "category":      r.category or "",
            "imageUrl":      r.image_url,
            "currentPrice":  r.current_price,
            "originalPrice": r.original_price,
            "discountPct":   r.discount_pct,
            "marginPct":     round((r.original_price - r.current_price) / r.current_price * 100, 1) if r.current_price else 0,
            "url":           r.url or "",
        }
        for r in rows
    ]

    sent_dev = send_deals_batch(deals, channel_id=settings.telegram_channel_dev) if settings.telegram_channel_dev else 0
    sent_prd = send_deals_batch(deals, channel_id=settings.telegram_channel_prd) if settings.telegram_channel_prd else 0
    notify_admin(f"✅ PriceHunter: DEV {sent_dev}/{len(deals)} | PRD {sent_prd}/{len(deals)} deals publicados")
    return {"sent_dev": sent_dev, "sent_prd": sent_prd, "total": len(deals)}


@app.task(name="generate_tiktok_content")
def generate_tiktok_content(min_discount: float = 35.0) -> dict:
    """Genera una imagen TikTok del mejor deal y la envía al admin por Telegram."""
    from app.notifications.tiktok_image import generate_tiktok_image, build_tiktok_caption
    from app.notifications.telegram import notify_admin, _telegram_api_url
    from sqlalchemy import text
    import httpx

    with Session(_engine) as session:
        row = session.execute(text("""
            SELECT sp.id, sp.store, p.name, p.brand, p.category,
                   COALESCE(p.image_url, '')           AS image_url,
                   CAST(sp.current_price  AS float)    AS current_price,
                   CAST(sp.original_price AS float)    AS original_price,
                   CAST(sp.discount_percentage AS float) AS discount_pct,
                   sp.url
            FROM store_products sp
            JOIN products p ON p.id = sp.product_id
            WHERE sp.in_stock = true
              AND sp.discount_percentage >= :min_discount
              AND sp.current_price > 0
              AND sp.original_price > 0
              AND p.image_url IS NOT NULL
              AND p.image_url != ''
            ORDER BY sp.discount_percentage DESC
            LIMIT 1
        """), {"min_discount": min_discount}).fetchone()

    if not row:
        notify_admin("TikTok: no hay deals con imagen para generar contenido.")
        return {"status": "no_deals"}

    deal = {
        "name":          row.name,
        "store":         row.store,
        "brand":         row.brand or "",
        "category":      row.category or "",
        "imageUrl":      row.image_url,
        "currentPrice":  row.current_price,
        "originalPrice": row.original_price,
        "discountPct":   row.discount_pct,
        "url":           row.url or "",
    }

    try:
        img_bytes = generate_tiktok_image(deal)
        caption   = build_tiktok_caption(deal)
    except Exception as exc:
        notify_admin(f"TikTok: error generando imagen — {exc}")
        return {"status": "error", "error": str(exc)}

    token    = settings.telegram_bot_token
    admin_id = settings.telegram_admin_id
    if not token or not admin_id:
        return {"status": "no_telegram_config"}

    try:
        with httpx.Client(timeout=30) as client:
            client.post(
                _telegram_api_url(token, "sendPhoto"),
                files={"photo": ("tiktok.jpg", img_bytes, "image/jpeg")},
                data={
                    "chat_id":    admin_id,
                    "caption":    f"🎬 *IMAGEN TIKTOK LISTA*\n\n{caption}",
                    "parse_mode": "Markdown",
                },
            )
    except Exception as exc:
        return {"status": "send_error", "error": str(exc)}

    return {"status": "ok", "deal": deal["name"], "store": deal["store"]}


@app.task(name="scrape_product_on_demand")
def scrape_product_on_demand(store_product_id: str) -> str:
    return f"on-demand scrape requested for {store_product_id}"


@app.task(name="cleanup_old_prices")
def cleanup_old_prices() -> str:
    from sqlalchemy import text
    with Session(_engine) as session:
        session.execute(text(
            "DELETE FROM price_history WHERE scraped_at < NOW() - INTERVAL '30 days'"
        ))
        session.commit()
    return "old price history cleaned"


@app.task(name="evaluate_alerts")
def evaluate_alerts(store_product_id: str, new_price: str) -> str:
    return f"evaluating alerts for {store_product_id} at {new_price}"
