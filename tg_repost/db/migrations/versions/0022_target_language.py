"""Язык публикации у целевой группы + язык у варианта рерайта.

Язык выбирается у ЦЕЛИ, а не у источника: один источник кормит и русские, и
англоязычные группы. Пост, уходящий в группы с разными языками, получает по
рерайту на каждый язык — отсюда язык и у варианта.

Существующим строкам проставляется `ru`: так решил владелец, и это сохраняет
текущее поведение до тех пор, пока язык у конкретной группы не переключат
руками.

Revision ID: 0022_target_language
Revises: 0021_rss_sources
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_target_language"
down_revision = "0021_rss_sources"
branch_labels = None
depends_on = None

_DEFAULT = "ru"


def upgrade() -> None:
    op.add_column(
        "target_groups",
        sa.Column("language", sa.String(length=8), nullable=False, server_default=_DEFAULT),
    )
    op.add_column(
        "post_rewrite_variants",
        sa.Column("language", sa.String(length=8), nullable=False, server_default=_DEFAULT),
    )
    # Индекс по языку варианта: публикация подбирает текст нужного языка на
    # КАЖДУЮ цель каждого поста, то есть это запрос горячего пути.
    op.create_index(
        "ix_post_rewrite_variants_language", "post_rewrite_variants", ["post_id", "language"],
    )


def downgrade() -> None:
    op.drop_index("ix_post_rewrite_variants_language", table_name="post_rewrite_variants")
    op.drop_column("post_rewrite_variants", "language")
    op.drop_column("target_groups", "language")
