"""Centro de Configuración: system_configurations + bitácora de cambios

Revision ID: a1c7e5d9b204
Revises: 3f6e3b8d4b6c
Create Date: 2026-08-07 00:00:00.000000

Tablas nuevas y aditivas: no tocan ninguna tabla existente.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a1c7e5d9b204"
down_revision = "3f6e3b8d4b6c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_configurations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("environment", sa.String(length=20), nullable=False, server_default="development"),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("value_type", sa.String(length=20), nullable=False, server_default="text"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("environment", "category", "key", name="uq_system_config_env_cat_key"),
    )
    op.create_index(op.f("ix_system_configurations_environment"), "system_configurations", ["environment"])
    op.create_index(op.f("ix_system_configurations_category"), "system_configurations", ["category"])

    op.create_table(
        "system_configuration_audit",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("environment", sa.String(length=20), nullable=False, server_default="development"),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_system_configuration_audit_environment"), "system_configuration_audit", ["environment"])
    op.create_index(op.f("ix_system_configuration_audit_category"), "system_configuration_audit", ["category"])
    op.create_index(op.f("ix_system_configuration_audit_created_at"), "system_configuration_audit", ["created_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_system_configuration_audit_created_at"), table_name="system_configuration_audit")
    op.drop_index(op.f("ix_system_configuration_audit_category"), table_name="system_configuration_audit")
    op.drop_index(op.f("ix_system_configuration_audit_environment"), table_name="system_configuration_audit")
    op.drop_table("system_configuration_audit")

    op.drop_index(op.f("ix_system_configurations_category"), table_name="system_configurations")
    op.drop_index(op.f("ix_system_configurations_environment"), table_name="system_configurations")
    op.drop_table("system_configurations")
