import redis
from app.core.config import get_settings
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

settings = get_settings()
r = redis.from_url(settings.redis_url)
engine = create_engine(settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://"))

with Session(engine) as session:
    rows = session.execute(text("""
        WITH hist AS (
            SELECT store_product_id, AVG(price) AS avg_hist_price, COUNT(*) AS hist_count
            FROM price_history
            WHERE price > 0 AND scraped_at < NOW() - INTERVAL '12 hours'
            GROUP BY store_product_id
        )
        SELECT sp.id, sp.store, p.name,
               CAST(sp.current_price AS float) AS cp,
               CAST(sp.original_price AS float) AS op,
               CAST(sp.discount_percentage AS float) AS disc,
               sp.in_stock,
               COALESCE(h.hist_count,0) AS hc,
               CAST(COALESCE(h.avg_hist_price,0) AS float) AS ah
        FROM store_products sp
        JOIN products p ON p.id = sp.product_id
        LEFT JOIN hist h ON h.store_product_id = sp.id
        WHERE sp.current_price > 0 AND sp.in_stock = true
          AND (
            (h.hist_count >= 1 AND h.avg_hist_price > 0 AND sp.current_price < h.avg_hist_price * 0.85)
            OR
            (sp.discount_percentage >= 70 AND sp.original_price > 0 AND sp.current_price < sp.original_price * 0.30)
          )
        ORDER BY disc DESC LIMIT 15
    """)).fetchall()

print(f"Total calificados: {len(rows)}")
for row in rows:
    key = f"tg_notified:{row.id}"
    notif = bool(r.exists(key))
    estado = "YA" if notif else "NEW"
    print(f"{estado} | {row.store} | {row.name[:35]} | -{row.disc:.0f}% | cp={row.cp} op={row.op}")
