-- Objetos creados a mano en Supabase para que la API pueda servir la vista de
-- ofertas en tiempos razonables. NO se aplican solos: el arranque no ejecuta
-- alembic (la base ya esta migrada). Si algun dia se recrea la base desde cero,
-- hay que volver a ejecutarlos.
--
-- Contexto: cada peticion recalculaba la mediana historica sobre 1,9M filas de
-- price_history (19s) y traia 98.000 filas a memoria para pintar 50. 120s por
-- request. Con estos dos objetos, la pagina se sirve en menos de un segundo.

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

-- La refresca `scrape_all_stores` al terminar (ver app/tasks/celery_app.py).
-- A mano:
--   REFRESH MATERIALIZED VIEW CONCURRENTLY price_medians;

-- 2) Indice para el orden por descuento -----------------------------------
-- Parcial: solo las filas que la vista muestra. 6 MB, y baja la consulta de
-- la pagina de 0,91s a 0,56s.
CREATE INDEX IF NOT EXISTS ix_sp_ofertas
    ON store_products (discount_percentage DESC NULLS LAST, id)
    WHERE in_stock = true AND current_price > 0 AND current_price < 100000;
