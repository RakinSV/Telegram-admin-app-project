"""Сюжеты: одна новость из нескольких источников (F51).

Раньше повтор помечался `duplicate` и терялся. Но повтор из НЕЗАВИСИМОГО
источника — подтверждение факта, а не мусор: на нём работает фактчек
редакции (F40) и сравнение версий (F24). Теперь повторы собираются в
кластер вокруг первого пришедшего поста.

Revision ID: 0028_story_clusters
Revises: 0027_contests
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028_story_clusters"
down_revision = "0027_contests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "story_clusters",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Без ForeignKey на posts.id намеренно: обратная ссылка
        # posts.cluster_id -> story_clusters.id уже есть, и пара FK замкнула
        # бы цикл, который SQLite не разорвать (нет ALTER ADD CONSTRAINT).
        sa.Column("primary_post_id", sa.Integer(), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_story_clusters_primary", "story_clusters", ["primary_post_id"])

    op.add_column("posts", sa.Column("cluster_id", sa.Integer(), nullable=True))
    op.create_index("ix_posts_cluster_id", "posts", ["cluster_id"])


def downgrade() -> None:
    op.drop_index("ix_posts_cluster_id", table_name="posts")
    op.drop_column("posts", "cluster_id")
    op.drop_index("ix_story_clusters_primary", table_name="story_clusters")
    op.drop_table("story_clusters")
