"""Поддержка: единый инбокс обращений (F68).

Вопрос, написанный боту в личку, до сих пор не превращался ни во что —
терялся среди прочих апдейтов. Теперь переписка живёт в системе и видна в
админке.

ОДИН ТРЕД НА ЧЕЛОВЕКА, а не на обращение: человек не мыслит «тикетами», он
пишет, дописывает и возвращается через неделю. Нарезка по таймауту породила
бы три треда об одном и том же.

Revision ID: 0040_support
Revises: 0039_content_calendar
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0040_support"
down_revision = "0039_content_calendar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_threads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        # Отдельный флаг, а не сравнение дат: «прочитано» — решение
        # оператора, а не факт открытия страницы.
        sa.Column("has_unread", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_support_thread_user"),
    )
    op.create_index("ix_support_threads_user_id", "support_threads", ["user_id"])
    op.create_index("ix_support_threads_status", "support_threads", ["status"])
    op.create_index(
        "ix_support_threads_last_message_at", "support_threads", ["last_message_at"],
    )

    op.create_table(
        "support_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "thread_id",
            sa.Integer(),
            sa.ForeignKey("support_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("direction", sa.String(4), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("author", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_support_messages_thread_id", "support_messages", ["thread_id"])


def downgrade() -> None:
    op.drop_index("ix_support_messages_thread_id", table_name="support_messages")
    op.drop_table("support_messages")
    op.drop_index("ix_support_threads_last_message_at", table_name="support_threads")
    op.drop_index("ix_support_threads_status", table_name="support_threads")
    op.drop_index("ix_support_threads_user_id", table_name="support_threads")
    op.drop_table("support_threads")
