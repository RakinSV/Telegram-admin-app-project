"""phase 2: source target override, embedding, post_stats

Revision ID: 0002_phase2
Revises: 0001_initial
Create Date: 2026-06-30
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_phase2"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # F12 — переопределение целей на источник.
    op.add_column("sources", sa.Column("target_chat_ids", sa.String(length=512), nullable=True))

    # F13 — эмбеддинг оригинала для семантического дубль-чека.
    op.add_column("posts", sa.Column("embedding", sa.LargeBinary(), nullable=True))

    # F14 — чат опубликованного поста (для сбора просмотров).
    op.add_column("posts", sa.Column("posted_chat_id", sa.BigInteger(), nullable=True))

    # F14 — снимки метрик постов.
    op.create_table(
        "post_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("posts.id"), nullable=False),
        sa.Column("view_count", sa.Integer(), nullable=True),
        sa.Column("forward_count", sa.Integer(), nullable=True),
        sa.Column("reaction_count", sa.Integer(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_post_stats_post_id", "post_stats", ["post_id"])


def downgrade() -> None:
    op.drop_index("ix_post_stats_post_id", table_name="post_stats")
    op.drop_table("post_stats")
    with op.batch_alter_table("posts") as batch:
        batch.drop_column("posted_chat_id")
        batch.drop_column("embedding")
    with op.batch_alter_table("sources") as batch:
        batch.drop_column("target_chat_ids")
