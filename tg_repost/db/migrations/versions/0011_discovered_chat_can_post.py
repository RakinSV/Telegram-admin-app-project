"""F08-доп.: флаг "может ли бот постить" на обнаруженных чатах

Заполняется из апдейта `my_chat_member` — значим только для каналов, где
обычный участник (не администратор с `can_post_messages`) никогда не может
слать сообщения от своего имени. Позволяет предупредить в /targets ДО того,
как чат добавят как цель, а не постфактум через FAILED-статус первого поста.

Revision ID: 0011_discovered_chat_can_post
Revises: 0010_post_variants
Create Date: 2026-07-16
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_discovered_chat_can_post"
down_revision: str | None = "0010_post_variants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("discovered_chats", sa.Column("can_post", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("discovered_chats") as batch_op:
        batch_op.drop_column("can_post")
