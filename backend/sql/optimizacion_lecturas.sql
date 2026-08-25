-- Objetos creados a mano en Supabase para que la API sirva las vistas en
-- tiempos razonables. NO se aplican solos: el arranque no ejecuta alembic (la
-- base ya esta migrada). Si algun dia se recrea la base, hay que ejecutarlos.
--
-- De donde viene esto: cada peticion recalculaba la mediana historica sobre
-- 1,9M filas de price_history (19s) y traia 98.000 filas a memoria para pintar
-- 50. 120s por request, y la API acababa devolviendo los 7 productos de ejemplo.
-- Filtrar por "bajo su precio habitual" costaba 9s y ordenar por bajada real
-- 45s, porque ningun indice puede cubrir un calculo que nace de un JOIN.
-- Con las dos vistas de abajo, esas mismas consultas tardan 0,2-0,3s.

-- 1) Medianas historicas precalculadas -----------------------------------
-- El indice UNIQUE no es un capricho: REFRESH ... CONCURRENTLY lo exige, y sin
-- CONCURRENTLY el refresco bloquea las lecturas mientras dura.
CREATE MATERIALIZED VIEW IF NOT EXISTS price_medians AS
SELECT store_product_id,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price) AS median_price,
       COUNT(*)                                           AS hist_count
FROM price_history
WHERE price > 0
  AND price < 100000                        -- excluye precios basura (parsing corrupto)
  AND scraped_at < NOW() - INTERVAL '12 hours'
GROUP BY store_product_id;

CREATE UNIQUE INDEX IF NOT EXISTS ix_price_medians_sp ON price_medians (store_product_id);

-- 2) Ofertas con todo ya calculado ---------------------------------------
-- Debe crearse DESPUES de price_medians: lee de ella.
-- Su definicion vive en app/services/deal_service.py (_CALCULO_SNAPSHOT); si se
-- toca alli, hay que recrear la vista aqui.
CREATE MATERIALIZED VIEW IF NOT EXISTS deal_snapshot AS
WITH base AS (
    SELECT sp.id,
           sp.product_id,
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
SELECT * FROM calc;

CREATE UNIQUE INDEX IF NOT EXISTS ix_snap_id     ON deal_snapshot (id);
CREATE INDEX IF NOT EXISTS ix_snap_desc          ON deal_snapshot (discount_pct DESC NULLS LAST, id);
CREATE INDEX IF NOT EXISTS ix_snap_bajada        ON deal_snapshot (mkt_diff_pct DESC NULLS LAST, id) WHERE below_market;
CREATE INDEX IF NOT EXISTS ix_snap_store         ON deal_snapshot (store);
CREATE INDEX IF NOT EXISTS ix_snap_precio        ON deal_snapshot (current_price);

-- Las refresca `scrape_all_stores` al terminar (app/tasks/celery_app.py), en
-- este orden. A mano:
--   REFRESH MATERIALIZED VIEW CONCURRENTLY price_medians;
--   REFRESH MATERIALIZED VIEW CONCURRENTLY deal_snapshot;

-- 3) Indice para el orden por descuento -----------------------------------
CREATE INDEX IF NOT EXISTS ix_sp_ofertas
    ON store_products (discount_percentage DESC NULLS LAST, id)
    WHERE in_stock = true AND current_price > 0 AND current_price < 100000;

-- 4) Espacio en disco ------------------------------------------------------
-- La base llego a 1.088 MB y Supabase empezo a fallar con "No space left on
-- device" en los archivos temporales. Se solto ix_price_history_sp_scraped
-- (170 MB, usado 436 veces; el ix_price_history_sp de 37 MB se usa 99.229 y se
-- queda). Si vuelve a apretar, lo siguiente es purgar price_history antiguo:
-- hay ~572k filas de mas de 30 dias, pero eso degrada las medianas.
--   DROP INDEX CONCURRENTLY IF EXISTS ix_price_history_sp_scraped;
