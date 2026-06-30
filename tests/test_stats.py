"""Тесты сводки статистики (F14): compute_stats_summary (Фаза 5.3 рефакторинг
text/data split, по образцу smart_schedule.py/growth.py)."""

from datetime import datetime, timedelta, timezone

from tg_repost.db.models import Post, PostKind, PostStat, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.scheduler.stats import compute_stats_summary, stats_summary


def _clear_posts() -> None:
    with session_scope() as session:
        session.query(PostStat).delete()
        session.query(Post).delete()


def test_compute_stats_summary_no_posts():
    _clear_posts()
    summary = compute_stats_summary(window_days=7)
    assert summary.published == 0
    assert summary.counted == 0
    assert summary.total_views == 0
    assert summary.avg_views == 0.0
    assert summary.top_post_id is None


def test_compute_stats_summary_aggregates_views_and_finds_top_post():
    _clear_posts()
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        low = Post(kind=PostKind.SOURCE, status=PostStatus.POSTED, posted_at=now)
        high = Post(kind=PostKind.SOURCE, status=PostStatus.POSTED, posted_at=now)
        session.add_all([low, high])
        session.flush()
        session.add(PostStat(post_id=low.id, view_count=10))
        session.add(PostStat(post_id=high.id, view_count=100))
        low_id, high_id = low.id, high.id

    summary = compute_stats_summary(window_days=7)
    assert summary.published == 2
    assert summary.counted == 2
    assert summary.total_views == 110
    assert summary.avg_views == 55.0
    assert summary.top_post_id == high_id
    assert summary.top_post_views == 100
    assert low_id != high_id  # обе записи реально различны


def test_compute_stats_summary_uses_latest_snapshot_per_post():
    _clear_posts()
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        post = Post(kind=PostKind.SOURCE, status=PostStatus.POSTED, posted_at=now)
        session.add(post)
        session.flush()
        session.add(PostStat(post_id=post.id, view_count=5, captured_at=now - timedelta(hours=2)))
        session.add(PostStat(post_id=post.id, view_count=50, captured_at=now))

    summary = compute_stats_summary(window_days=7)
    assert summary.counted == 1
    assert summary.total_views == 50


def test_compute_stats_summary_ignores_posts_outside_window():
    _clear_posts()
    old = datetime.now(timezone.utc) - timedelta(days=30)
    with session_scope() as session:
        post = Post(kind=PostKind.SOURCE, status=PostStatus.POSTED, posted_at=old)
        session.add(post)

    summary = compute_stats_summary(window_days=7)
    assert summary.published == 0


def test_stats_summary_text_no_posts():
    _clear_posts()
    text = stats_summary(window_days=7)
    assert "нет" in text


def test_stats_summary_text_includes_top_post():
    _clear_posts()
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        post = Post(kind=PostKind.SOURCE, status=PostStatus.POSTED, posted_at=now)
        session.add(post)
        session.flush()
        session.add(PostStat(post_id=post.id, view_count=42))
        post_id = post.id

    text = stats_summary(window_days=7)
    assert f"#{post_id}" in text
    assert "42" in text
