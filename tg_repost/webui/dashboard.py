"""Запросы для read-only дашборда веб-админки (F23, Фаза 5.1).

Чистые query-функции, без HTTP — переиспользуются роутом `/` из `app.py`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from tg_repost.db.models import Post, PostStatus
from tg_repost.db.session import session_scope


def post_status_funnel() -> dict[str, int]:
    """Количество постов по каждому статусу статус-машины (F05)."""
    with session_scope() as session:
        rows = session.query(Post.status, func.count(Post.id)).group_by(Post.status).all()
    return {status.value: count for status, count in rows}


def todays_rewrite_tokens() -> int:
    """Суммарные токены рерайта за текущие сутки (UTC)."""
    since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    with session_scope() as session:
        total = (
            session.query(func.sum(Post.rewrite_tokens))
            .filter(Post.created_at >= since)
            .scalar()
        )
    return total or 0


def recent_posts(limit: int = 20) -> list[Post]:
    """Последние посты по времени создания (любого статуса/вида)."""
    with session_scope() as session:
        return (
            session.query(Post).order_by(Post.created_at.desc()).limit(limit).all()
        )


def error_rate(window_days: int = 1) -> float:
    """Доля постов со статусом FAILED за период (0.0–1.0, 0.0 если постов нет)."""
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    with session_scope() as session:
        total = session.query(Post.id).filter(Post.created_at >= since).count()
        if total == 0:
            return 0.0
        failed = (
            session.query(Post.id)
            .filter(Post.created_at >= since, Post.status == PostStatus.FAILED)
            .count()
        )
    return failed / total
