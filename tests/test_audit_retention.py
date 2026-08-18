"""Горизонт журнала действий.

ЗАМЕР ВАЖНЕЕ ДОГАДКИ: на стенде в `audit_log` 47 записей за месяц — журнал не
создаёт никакого давления на диск, и «уборка ради места» здесь была бы
выдумкой. Ограничение стоит по другой причине: система работает без присмотра
годами, и таблица, не ограниченная НИЧЕМ, однажды становится проблемой в самый
неудобный момент. Отсюда и большой срок по умолчанию — журнал подотчётности
ценен именно тем, что помнит давнее.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tg_repost.db.models import AuditLog
from tg_repost.db.session import session_scope
from tg_repost.webui import audit


@pytest.fixture(autouse=True)
def _clean_audit():
    with session_scope() as session:
        session.query(AuditLog).delete()
    yield
    with session_scope() as session:
        session.query(AuditLog).delete()


def _record(age_days: float, action: str = "test_action") -> int:
    with session_scope() as session:
        row = AuditLog(
            action=action,
            created_at=datetime.now(timezone.utc) - timedelta(days=age_days),
        )
        session.add(row)
        session.flush()
        return row.id


def test_old_records_are_purged():
    old = _record(800)

    assert audit.purge_older_than(730) == 1

    with session_scope() as session:
        assert session.get(AuditLog, old) is None


def test_records_inside_the_horizon_stay():
    """Журнал подотчётности ценен давним: срок по умолчанию — два года."""
    recent = _record(700)

    assert audit.purge_older_than(730) == 0

    with session_scope() as session:
        assert session.get(AuditLog, recent) is not None


def test_zero_means_keep_everything():
    """Ноль — «не чистить», а не «стереть журнал». Перепутать эти два смысла
    в журнале безопасности — потерять его целиком одной опечаткой."""
    ancient = _record(5000)

    assert audit.purge_older_than(0) == 0

    with session_scope() as session:
        assert session.get(AuditLog, ancient) is not None


def test_negative_is_treated_as_off_too():
    ancient = _record(5000)

    assert audit.purge_older_than(-30) == 0

    with session_scope() as session:
        assert session.get(AuditLog, ancient) is not None
