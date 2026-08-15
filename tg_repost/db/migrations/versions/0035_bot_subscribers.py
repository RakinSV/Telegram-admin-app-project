"""Реестр подписчиков бота — кому вообще можно написать (F64).

ЭТО НЕ НАШЕ ОГРАНИЧЕНИЕ, А ПРАВИЛО TELEGRAM: бот не может написать первым.
Личная переписка открывается только когда человек сам нажал «Запустить» или
пришёл по deep-link. Без этой таблицы у рассылки нет ни одного получателя —
не потому, что мы чего-то не умеем, а потому, что писать некому.

Следствие, которое легко упустить: сегмент из 8000 участников группы может
быть достижим на сотню человек. Поэтому у рассылки всегда две цифры.

Revision ID: 0035_bot_subscribers
Revises: 0034_segments
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0035_bot_subscribers"
down_revision = "0034_segments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bot_subscribers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column("first_name", sa.String(255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        # Человек заблокировал бота — решение Telegram, снимается сам, когда
        # он снова напишет.
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default="0"),
        # Человек отписался кнопкой — его решение. С блокировкой не путать:
        # это разные вещи и снимаются по-разному.
        sa.Column("unsubscribed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_bot_subscriber"),
    )
    op.create_index("ix_bot_subscribers_user_id", "bot_subscribers", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_bot_subscribers_user_id", table_name="bot_subscribers")
    op.drop_table("bot_subscribers")
