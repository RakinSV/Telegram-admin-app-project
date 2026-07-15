"""F08-доп.: авто-обнаружение чатов, куда добавили репост-бота

Заполняется из апдейта `my_chat_member` (telegram/moderation_bot.py) —
избавляет от ручного поиска chat_id через сторонних ботов на странице
/targets в веб-админке.

Revision ID: 0009_discovered_chats
Revises: 0008_telethon_sessions
Create Date: 2026-07-15
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_discovered_chats"
down_revision: str | None = "0008_telethon_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discovered_chats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("chat_type", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_discovered_chats_chat_id", "discovered_chats", ["chat_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_discovered_chats_chat_id", table_name="discovered_chats")
    op.drop_table("discovered_chats")
