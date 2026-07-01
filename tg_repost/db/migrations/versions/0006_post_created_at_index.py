"""phase 5 audit: index on posts.created_at (dashboard query performance)

Дашборд (`webui/dashboard.py`) фильтрует/сортирует по `posts.created_at` на
каждой загрузке (`recent_posts`, `todays_rewrite_tokens`, `error_rate`) —
без индекса это full table scan, растущий вместе с числом постов и
выполняемый прямо в общем event loop (весь процесс — Telethon/бот/
планировщик/веб — живёт в одном потоке). Найдено при аудите Фазы 5.

Revision ID: 0006_post_created_at_index
Revises: 0005_phase5
Create Date: 2026-07-01
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_post_created_at_index"
down_revision: str | None = "0005_phase5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_posts_created_at", "posts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_posts_created_at", table_name="posts")
