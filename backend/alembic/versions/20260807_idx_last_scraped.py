"""Indice en store_products.last_scraped_at (Historial de Precios)

Revision ID: c3e9a4f7d158
Revises: b2d8f6e1c375
Create Date: 2026-08-07 00:00:00.000000

El listado de Historial ordena por `last_scraped_at DESC` para quedarse con los
candidatos mas recientes. Sin indice, Postgres hacia un Parallel Seq Scan de las
~137k filas de store_products y las ordenaba EN DISCO (external merge, 7-12 MB).
Con la base cargada eso superaba el statement_timeout de Supabase y la vista
devolvia 500.

EXPLAIN ANALYZE antes del indice: 4.436 ms (800 candidatos) / 2.840 ms (2.500),
casi todo en el Sort. El indice permite recorrer el orden ya materializado y
cortar con el LIMIT.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c3e9a4f7d158"
down_revision = "b2d8f6e1c375"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_store_products_last_scraped",
        "store_products",
        [sa.text("last_scraped_at DESC NULLS LAST")],
    )


def downgrade() -> None:
    op.drop_index("ix_store_products_last_scraped", table_name="store_products")
