"""Тесты агрегации суточной статистики Guardian (G11/G17)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from guardian.db.models import DailyStats, Member, ModerationLog
from guardian.db.session import session_scope
from guardian.services import daily_stats_repo

CHAT_ID = -100999


@pytest.fixture(autouse=True)
def _clear_tables():
    with session_scope() as session:
        session.query(DailyStats).delete()
        session.query(ModerationLog).delete()
        session.query(Member).delete()
    yield


def test_record_ai_call_creates_row_and_accumulates():
    daily_stats_repo.record_ai_call(CHAT_ID, 0.01)
    daily_stats_repo.record_ai_call(CHAT_ID, 0.02)
    with session_scope() as session:
        row = session.query(DailyStats).filter(DailyStats.chat_id == CHAT_ID).one()
        assert row.ai_calls == 2
        assert row.ai_cost_usd == pytest.approx(0.03)


def test_compute_and_store_counts_moderation_actions():
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        session.add_all(
            [
                ModerationLog(action="warn", user_id=1, chat_id=CHAT_ID, created_at=now),
                ModerationLog(action="delete_msg", user_id=1, chat_id=CHAT_ID, created_at=now),
                ModerationLog(action="delete_msg", user_id=2, chat_id=CHAT_ID, created_at=now),
                ModerationLog(action="mute", user_id=1, chat_id=CHAT_ID, created_at=now),
                ModerationLog(action="kick", user_id=3, chat_id=CHAT_ID, created_at=now),
                ModerationLog(action="ban", user_id=4, chat_id=CHAT_ID, created_at=now),
            ]
        )

    row = daily_stats_repo.compute_and_store_daily_stats(CHAT_ID)

    assert row.deleted_msgs == 2
    assert row.warnings == 1
    assert row.mutes == 1
    assert row.kicks == 1
    assert row.bans == 1


def test_compute_and_store_counts_new_and_verified_members():
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        session.add_all(
            [
                Member(user_id=1, chat_id=CHAT_ID, join_date=now, is_verified=True),
                Member(user_id=2, chat_id=CHAT_ID, join_date=now, is_verified=False),
                Member(
                    user_id=3, chat_id=CHAT_ID, join_date=now - timedelta(days=5), is_verified=True
                ),
            ]
        )

    row = daily_stats_repo.compute_and_store_daily_stats(CHAT_ID)

    assert row.new_members == 2  # только сегодняшние
    assert row.verified_members == 1


def test_compute_and_store_does_not_touch_ai_fields():
    daily_stats_repo.record_ai_call(CHAT_ID, 0.05)
    row = daily_stats_repo.compute_and_store_daily_stats(CHAT_ID)
    assert row.ai_calls == 1
    assert row.ai_cost_usd == pytest.approx(0.05)


def test_compute_and_store_is_idempotent_recompute():
    """Повторный вызов за тот же день должен пересчитать, а не удвоить."""
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        session.add(ModerationLog(action="ban", user_id=1, chat_id=CHAT_ID, created_at=now))

    daily_stats_repo.compute_and_store_daily_stats(CHAT_ID)
    daily_stats_repo.compute_and_store_daily_stats(CHAT_ID)

    with session_scope() as session:
        rows = session.query(DailyStats).filter(DailyStats.chat_id == CHAT_ID).all()
        assert len(rows) == 1
        assert rows[0].bans == 1


def test_compute_and_store_scoped_to_chat():
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        session.add_all(
            [
                ModerationLog(action="ban", user_id=1, chat_id=CHAT_ID, created_at=now),
                ModerationLog(action="ban", user_id=2, chat_id=-200, created_at=now),
            ]
        )

    row = daily_stats_repo.compute_and_store_daily_stats(CHAT_ID)
    assert row.bans == 1


def test_daily_stats_range_returns_ascending_order():
    today = datetime.now(timezone.utc).date()
    with session_scope() as session:
        session.add_all(
            [
                DailyStats(date=today - timedelta(days=2), chat_id=CHAT_ID, bans=1),
                DailyStats(date=today, chat_id=CHAT_ID, bans=2),
                DailyStats(date=today - timedelta(days=1), chat_id=CHAT_ID, bans=3),
            ]
        )

    rows = daily_stats_repo.daily_stats_range(CHAT_ID, days=7)
    assert [r.bans for r in rows] == [1, 3, 2]


def test_daily_stats_range_excludes_old_entries():
    today = datetime.now(timezone.utc).date()
    with session_scope() as session:
        session.add(DailyStats(date=today - timedelta(days=30), chat_id=CHAT_ID, bans=9))

    rows = daily_stats_repo.daily_stats_range(CHAT_ID, days=7)
    assert rows == []
