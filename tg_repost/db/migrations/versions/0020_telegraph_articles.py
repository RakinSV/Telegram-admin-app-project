"""Статьи на Telegraph: формат публикации у источника + URL статьи у поста

`sources.post_format`: "post" (как было) | "article" (лонгрид на telegra.ph,
в канал уходит тизер со ссылкой). NULL у существующих источников = "post",
то есть поведение всех уже заведённых источников не меняется.

`posts.telegraph_url`: адрес опубликованной страницы. NULL — обычный пост.

Revision ID: 0020_telegraph_articles
Revises: 0019_post_link_content_info
Create Date: 2026-07-21
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_telegraph_articles"
down_revision: str | None = "0019_post_link_content_info"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("post_format", sa.String(length=16), nullable=True))
    op.add_column("posts", sa.Column("telegraph_url", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column("posts", "telegraph_url")
    op.drop_column("sources", "post_format")
