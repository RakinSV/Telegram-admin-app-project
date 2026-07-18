"""Тест ежедневной джобы `bot.py::_finalize_yesterday_stats` (G17)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from guardian import settings_store
from guardian.bot import _finalize_yesterday_stats
from guardian.config import invalidate_settings_cache
from guardian.db.models import BotConfig, DailyStats, ModerationLog
from guardian.db.session import session_scope

CHAT_ID = -100123  # GUARDIAN_GROUP_ID из tests/conftest.py


@pytest.fixture(autouse=True)
def _clear_tables():
    with session_scope() as session:
        session.query(DailyStats).delete()
        session.query(ModerationLog).delete()
        session.query(BotConfig).delete()
    invalidate_settings_cache()
    settings_store.sync_protected_chat_ids([CHAT_ID])  # F28: список, не одна группа
    yield


def test_finalize_yesterday_stats_writes_row_for_yesterday():
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    with session_scope() as session:
        session.add(ModerationLog(action="ban", user_id=1, chat_id=CHAT_ID, created_at=yesterday))

    _finalize_yesterday_stats()

    with session_scope() as session:
        row = session.query(DailyStats).filter(DailyStats.chat_id == CHAT_ID).one()
        assert row.date == yesterday.date()
        assert row.bans == 1


def test_no_protected_chats_is_noop():
    """F28: пустой protected_chat_ids — штатный no-op, не ошибка."""
    settings_store.sync_protected_chat_ids([])
    _finalize_yesterday_stats()  # не должно упасть
    with session_scope() as session:
        assert session.query(DailyStats).count() == 0


def test_processes_each_protected_chat_independently():
    other_chat_id = -100456
    settings_store.sync_protected_chat_ids([CHAT_ID, other_chat_id])
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    with session_scope() as session:
        session.add(ModerationLog(action="ban", user_id=1, chat_id=CHAT_ID, created_at=yesterday))
        session.add(ModerationLog(action="kick", user_id=2, chat_id=other_chat_id, created_at=yesterday))

    _finalize_yesterday_stats()

    with session_scope() as session:
        chat_ids_written = {row.chat_id for row in session.query(DailyStats).all()}
        assert chat_ids_written == {CHAT_ID, other_chat_id}
