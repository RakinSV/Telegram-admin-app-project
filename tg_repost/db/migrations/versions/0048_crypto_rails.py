"""Приём крипты: несколько способов, привязка к группам (F70).

Несколько способов ОДНОВРЕМЕННО — требование владельца: у разных групп
разные условия и разные кошельки. Поэтому таблица, а не настройка.

Товар получает `chat_id`, иначе привязку кошелька к группе не к чему
прицепить: заказ рождается из товара, а не из чата.

Revision ID: 0048_crypto_rails
Revises: 0047_api_and_webhooks
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0048_crypto_rails"
down_revision = "0047_api_and_webhooks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crypto_rails",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("credential_encrypted", sa.Text(), nullable=False),
        sa.Column("public_address", sa.String(128), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_crypto_rails_kind", "crypto_rails", ["kind"])

    op.add_column("products", sa.Column("chat_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_products_chat_id", "products", ["chat_id"])

    op.add_column(
        "target_groups", sa.Column("crypto_rail_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("target_groups", "crypto_rail_id")
    op.drop_index("ix_products_chat_id", table_name="products")
    op.drop_column("products", "chat_id")
    op.drop_index("ix_crypto_rails_kind", table_name="crypto_rails")
    op.drop_table("crypto_rails")
