"""Тест ежедневной джобы `bot.py::_finalize_yesterday_stats` (G17)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from guardian.bot import _finalize_yesterday_stats
from guardian.db.models import DailyStats, ModerationLog
from guardian.db.session import session_scope

CHAT_ID = -100123  # GUARDIAN_GROUP_ID из tests/conftest.py


@pytest.fixture(autouse=True)
def _clear_tables():
    with session_scope() as session:
        session.query(DailyStats).delete()
        session.query(ModerationLog).delete()
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
