"""Магазин в боте: товары и заказы (F69 + F70).

Цена в МИНИМАЛЬНЫХ единицах целым числом: так требует Bot Payments API, и
так же не возникает классической ошибки денег на дробных рублях.

Revision ID: 0045_shop
Revises: 0044_affiliate
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0045_shop"
down_revision = "0044_affiliate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="RUB"),
        sa.Column("stock", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("is_physical", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False,
        ),
        sa.Column("product_name", sa.String(128), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="RUB"),
        sa.Column("status", sa.String(16), nullable=False, server_default="new"),
        sa.Column("charge_id", sa.String(128), nullable=True),
        sa.Column("shipping", sa.Text(), nullable=True),
        sa.Column("is_oversold", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_orders_user_id", "orders", ["user_id"])
    op.create_index("ix_orders_product_id", "orders", ["product_id"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_charge_id", "orders", ["charge_id"])


def downgrade() -> None:
    op.drop_table("orders")
    op.drop_table("products")
