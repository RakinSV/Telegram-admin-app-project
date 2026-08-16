"""Партнёрские начисления поверх рефералов (F67).

Журнал, а не баланс: баланс партнёра — это сумма строк. Поле пришлось бы
менять при каждой оплате, возврате и выплате, и любая потерянная правка
расходилась бы с историей навсегда.

Revision ID: 0044_affiliate
Revises: 0043_payments
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0044_affiliate"
down_revision = "0043_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "affiliate_rewards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("partner_user_id", sa.BigInteger(), nullable=False),
        sa.Column("payer_user_id", sa.BigInteger(), nullable=True),
        sa.Column("payment_event_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "payment_event_id", "kind", name="uq_affiliate_reward",
        ),
    )
    op.create_index("ix_affiliate_rewards_kind", "affiliate_rewards", ["kind"])
    op.create_index(
        "ix_affiliate_rewards_partner_user_id", "affiliate_rewards", ["partner_user_id"],
    )
    op.create_index(
        "ix_affiliate_rewards_partner", "affiliate_rewards",
        ["partner_user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("affiliate_rewards")
