"""RSS как входящий источник наравне с Telegram-каналами

`sources.kind`: NULL/"telegram" — канал (поведение существующих строк не
меняется), "rss" — лента, её URL лежит в channel_username (колонка уже
UNIQUE, а лента опознаётся именно адресом).

Индекс на posts.source_link: по нему идёт дедупликация записей ленты на
каждом опросе, без индекса это полный скан таблицы постов раз в N минут.

Revision ID: 0021_rss_sources
Revises: 0020_telegraph_articles
Create Date: 2026-07-21
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_rss_sources"
down_revision: str | None = "0020_telegraph_articles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("kind", sa.String(length=16), nullable=True))
    op.create_index("ix_sources_kind", "sources", ["kind"])
    op.create_index("ix_posts_source_link", "posts", ["source_link"])


def downgrade() -> None:
    op.drop_index("ix_posts_source_link", table_name="posts")
    op.drop_index("ix_sources_kind", table_name="sources")
    op.drop_column("sources", "kind")
