"""F16-доп.: что именно прочитано по ссылке из поста

Две колонки на posts: какой URL реально открылся и сколько символов статьи
уехало в модель. Без них владелец, глядя на слабый рерайт, не мог отличить
«модель работала по полной статье и всё равно вышло плохо» от «статью не
удалось открыть, переписан один короткий тизер» — а это диаметрально разные
починки (править промпт против чинить доступ к сайту).

NULL у старых постов — корректное «неизвестно»: переход мог не выполняться
или ни одна ссылка не открылась, задним числом это не восстановить.

Revision ID: 0019_post_link_content_info
Revises: 0018_ad_revenue
Create Date: 2026-07-21
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_post_link_content_info"
down_revision: str | None = "0018_ad_revenue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("link_source_url", sa.String(length=1024), nullable=True))
    op.add_column("posts", sa.Column("link_content_chars", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("posts", "link_content_chars")
    op.drop_column("posts", "link_source_url")
