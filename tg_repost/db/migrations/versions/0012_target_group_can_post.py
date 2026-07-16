"""F08-доп.: флаг "может ли бот постить" на уже добавленных целевых группах

Аналог DiscoveredChat.can_post (миграция 0011), но синхронизируется и ПОСЛЕ
того, как чат уже стал целью публикации — раньше отзыв прав бота на уже
добавленную цель нигде не отображался, только тихий провал публикации.

Revision ID: 0012_target_group_can_post
Revises: 0011_discovered_chat_can_post
Create Date: 2026-07-16
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_target_group_can_post"
down_revision: str | None = "0011_discovered_chat_can_post"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("target_groups", sa.Column("can_post", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("target_groups") as batch_op:
        batch_op.drop_column("can_post")
