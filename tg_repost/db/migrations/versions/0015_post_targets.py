"""F29: таблица post_targets — результат публикации поста в каждую цель

Раньше `Post.posted_message_id`/`posted_chat_id` хранили только ПЕРВУЮ
успешную цель (см. `telegram/publisher.py::publish_post`) — F29
(редактирование/удаление/закрепление уже опубликованного поста) требует
знать ВСЕ цели. Одноразовая миграция данных: для уже опубликованных постов
переносим известную первую цель в новую таблицу (единственное, что у нас
есть о прошлых публикациях — остальные цели того поста, если их было
несколько, исторически не отслеживались и не восстановимы).

Revision ID: 0015_post_targets
Revises: 0014_target_group_guardian_can_moderate
Create Date: 2026-07-18
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_post_targets"
down_revision: str | None = "0014_target_group_guardian_can_moderate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "post_targets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("posts.id"), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("error", sa.String(length=512), nullable=True),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_post_targets_post_id", "post_targets", ["post_id"])

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO post_targets (post_id, chat_id, message_id, ok, pinned, created_at)
            SELECT id, posted_chat_id, posted_message_id, 1, 0, posted_at
            FROM posts
            WHERE posted_chat_id IS NOT NULL AND posted_message_id IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_post_targets_post_id", table_name="post_targets")
    op.drop_table("post_targets")
