"""Рассылки по сегменту (F64).

Отдельно от `queued_tasks` намеренно: задача — это механика (курсор,
попытки, аренда) и живёт до завершения, а рассылка — документ, который
владельцу нужен и через месяц. Смешав их, мы либо потеряли бы историю
вместе с выполненными задачами, либо превратили бы служебную таблицу
очереди в хранилище текстов.

Revision ID: 0036_broadcasts
Revises: 0035_bot_subscribers
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036_broadcasts"
down_revision = "0035_bot_subscribers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "broadcasts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("segment_id", sa.Integer(), nullable=True),
        # Имя сегмента на момент отправки: его могут переименовать или
        # удалить, а отчёт должен остаться читаемым.
        sa.Column("segment_name", sa.String(128), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="planned"),
        # Снимок на момент запуска: разрыв между этими числами объясняет
        # владельцу, почему «отправлено 120 из 8000» — это не сбой.
        sa.Column("segment_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reachable_size", sa.Integer(), nullable=False, server_default="0"),
        # Счётчики раздельные: доставлено, заблокировал бота, прочие ошибки.
        # Одна цифра «не дошло» скрыла бы, что именно происходит.
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_broadcasts_segment_id", "broadcasts", ["segment_id"])
    op.create_index("ix_broadcasts_status", "broadcasts", ["status"])


def downgrade() -> None:
    op.drop_index("ix_broadcasts_status", table_name="broadcasts")
    op.drop_index("ix_broadcasts_segment_id", table_name="broadcasts")
    op.drop_table("broadcasts")
