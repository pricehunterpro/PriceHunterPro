"""Precio con tarjeta (CMR/Única) en store_products

Revision ID: b2d8f6e1c375
Revises: a1c7e5d9b204
Create Date: 2026-08-07 00:00:00.000000

Columna aditiva y nullable: las filas existentes quedan en NULL hasta el próximo
scrape, y ninguna consulta actual se ve afectada.

Motivo: los tres scrapers del grupo Falabella descartaban `cmrPrice` por no ser
precio público, y con eso se perdían los glitches que sí se viralizan (HP Victus
a S/499 con CMR mientras el precio internet era S/3.139; JVC 75" a S/599,90 con
CMR contra S/2.099,90 internet — este último en Sodimac, que sí se estaba
raspando y aun así lo registró como un -22,8% irrelevante).
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b2d8f6e1c375"
down_revision = "a1c7e5d9b204"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("store_products", sa.Column("card_price", sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("store_products", "card_price")
