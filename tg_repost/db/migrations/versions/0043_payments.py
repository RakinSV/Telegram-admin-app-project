"""Платный доступ: журнал операций и подписки (F49).

Журнал append-only: оплата приходит апдейтом, апдейт может продублироваться,
и решение «выдать доступ» по текущему состоянию выдало бы его дважды.
Ключ идемпотентности — (kind, charge_id, period_end); `period_end` NOT NULL,
потому что в SQL уникальность не срабатывает на NULL.

Revision ID: 0043_payments
Revises: 0042_ad_marking
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0043_payments"
down_revision = "0042_ad_marking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("charge_id", sa.String(128), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="XTR"),
        sa.Column("invoice_payload", sa.String(255), nullable=True),
        sa.Column("is_recurring", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("is_first_recurring", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        # NOT NULL, как в модели. Старые таблицы разошлись с моделями именно
        # на таких колонках (см. `tests/test_schema_drift.py`); новые таблицы
        # эту историю не продолжают.
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kind", "charge_id", "period_end", name="uq_payment_event"),
    )
    op.create_index("ix_payment_events_kind", "payment_events", ["kind"])
    op.create_index("ix_payment_events_charge_id", "payment_events", ["charge_id"])
    op.create_index("ix_payment_events_user_id", "payment_events", ["user_id"])
    op.create_index("ix_payment_events_user", "payment_events", ["user_id", "created_at"])

    op.create_table(
        "channel_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("paid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("charge_id", sa.String(128), nullable=True),
        sa.Column("invite_link", sa.String(255), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("chat_id", "user_id", name="uq_channel_subscription"),
    )
    op.create_index("ix_channel_subscriptions_chat_id", "channel_subscriptions", ["chat_id"])
    op.create_index("ix_channel_subscriptions_user_id", "channel_subscriptions", ["user_id"])
    op.create_index("ix_channel_subscriptions_status", "channel_subscriptions", ["status"])
    op.create_index(
        "ix_channel_subscriptions_paid_until", "channel_subscriptions", ["paid_until"],
    )


def downgrade() -> None:
    op.drop_table("channel_subscriptions")
    op.drop_table("payment_events")
