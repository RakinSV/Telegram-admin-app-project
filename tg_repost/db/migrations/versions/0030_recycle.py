"""Повтор выстреливших постов — recycling (F55).

Почти бесплатный охват из уже проверенного контента: данные для отбора топа
и так лежат в growth-трекере (F22) и метриках (F14/F31), не хватало только
постановки повтора в очередь.

Самоссылка `posts.recycled_from_id -> posts.id`, а не отдельная таблица:
связь один-к-одному и без собственных атрибутов. Она же служит признаком
«этот пост уже повторяли» — наличие строки с `recycled_from_id = X` закрывает
X от повторного отбора, отдельный флаг не нужен.

Revision ID: 0030_recycle
Revises: 0029_source_filters
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030_recycle"
down_revision = "0029_source_filters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Без именованного FK-констрейнта: SQLite не умеет ALTER ADD CONSTRAINT,
    # и здесь достаточно индекса — по нему и идёт проверка «уже повторяли».
    # Тот же приём, что в 0028 для story_clusters.primary_post_id.
    op.add_column("posts", sa.Column("recycled_from_id", sa.Integer(), nullable=True))
    op.create_index("ix_posts_recycled_from_id", "posts", ["recycled_from_id"])


def downgrade() -> None:
    op.drop_index("ix_posts_recycled_from_id", table_name="posts")
    op.drop_column("posts", "recycled_from_id")
