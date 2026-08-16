"""Заказ помнит, каким кошельком за него платят (F70).

Кошелёк хранится В ЗАКАЗЕ, а не берётся заново по товару: владелец может
переназначить кошелёк группы, пока счёт висит неоплаченным, и проверять
тогда надо СТАРЫЙ — деньги придут туда, куда человеку показали ссылку.

Revision ID: 0049_order_crypto
Revises: 0048_crypto_rails
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0049_order_crypto"
down_revision = "0048_crypto_rails"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("crypto_rail_id", sa.Integer(), nullable=True))
    op.add_column(
        "orders", sa.Column("crypto_invoice_id", sa.String(128), nullable=True),
    )
    op.add_column("orders", sa.Column("crypto_amount", sa.String(32), nullable=True))
    op.add_column("orders", sa.Column("crypto_asset", sa.String(16), nullable=True))
    op.create_index("ix_orders_crypto_invoice_id", "orders", ["crypto_invoice_id"])


def downgrade() -> None:
    op.drop_index("ix_orders_crypto_invoice_id", table_name="orders")
    op.drop_column("orders", "crypto_asset")
    op.drop_column("orders", "crypto_amount")
    op.drop_column("orders", "crypto_invoice_id")
    op.drop_column("orders", "crypto_rail_id")
