"""Тесты системы варнов и эскалации Guardian (G05)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from guardian.config import invalidate_settings_cache
from guardian.db.models import Member, ModerationLog, Warning
from guardian.db.session import session_scope
from guardian.services.warn_system import add_warn, reset_expired_warns


def _clear() -> None:
    with session_scope() as session:
        session.query(Warning).delete()
        session.query(ModerationLog).delete()
        session.query(Member).delete()


@pytest.fixture(autouse=True)
def _isolated_thresholds(monkeypatch):
    monkeypatch.setenv("WARN_THRESHOLD_MUTE", "2")
    monkeypatch.setenv("WARN_THRESHOLD_KICK", "3")
    monkeypatch.setenv("WARN_THRESHOLD_BAN", "4")
    invalidate_settings_cache()
    _clear()
    yield
    _clear()
    invalidate_settings_cache()


async def test_add_warn_increments_count_no_escalation_on_first_warn():
    bot = AsyncMock()
    count = await add_warn(bot, user_id=1, chat_id=-100, reason="test")
    assert count == 1
    bot.restrict_chat_member.assert_not_awaited()
    bot.ban_chat_member.assert_not_awaited()


async def test_add_warn_reaches_mute_threshold():
    bot = AsyncMock()
    await add_warn(bot, user_id=1, chat_id=-100, reason="t1")
    count = await add_warn(bot, user_id=1, chat_id=-100, reason="t2")
    assert count == 2
    bot.restrict_chat_member.assert_awaited_once()
    bot.ban_chat_member.assert_not_awaited()


async def test_add_warn_reaches_kick_threshold():
    bot = AsyncMock()
    count = 0
    for _ in range(3):
        count = await add_warn(bot, user_id=1, chat_id=-100, reason="t")
    assert count == 3
    bot.ban_chat_member.assert_awaited_once()
    bot.unban_chat_member.assert_awaited_once()


async def test_add_warn_reaches_ban_threshold():
    # Пороги последовательны (mute=2 < kick=3 < ban=4) — 4 варна подряд одному
    # пользователю проходят ВСЕ ступени эскалации по пути, не только финальный
    # бан: warn2 → mute, warn3 → kick (ban_chat_member+unban_chat_member —
    # это и есть механизм кика в Bot API), warn4 → финальный бан (ещё один
    # ban_chat_member, уже без unban). Поэтому ban_chat_member вызывается
    # ДВАЖДЫ к этому моменту — не баг, а суммарный эффект пройденных ступеней.
    bot = AsyncMock()
    count = 0
    for _ in range(4):
        count = await add_warn(bot, user_id=1, chat_id=-100, reason="t")
    assert count == 4
    assert bot.ban_chat_member.await_count == 2
    assert bot.unban_chat_member.await_count == 1
    with session_scope() as session:
        member = (
            session.query(Member)
            .filter(Member.user_id == 1, Member.chat_id == -100)
            .one()
        )
        assert member.is_banned is True


async def test_add_warn_records_warning_and_moderation_log():
    bot = AsyncMock()
    await add_warn(
        bot, user_id=1, chat_id=-100, reason="стоп-слово: тест", issued_by="auto"
    )
    with session_scope() as session:
        warnings = session.query(Warning).filter(Warning.user_id == 1).all()
        logs = (
            session.query(ModerationLog)
            .filter(ModerationLog.user_id == 1, ModerationLog.action == "warn")
            .all()
        )
    assert len(warnings) == 1
    assert warnings[0].reason == "стоп-слово: тест"
    assert len(logs) == 1


def test_reset_expired_warns_resets_only_old_ones():
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        session.add_all(
            [
                Member(
                    user_id=1,
                    chat_id=-100,
                    warn_count=2,
                    last_warn_date=now - timedelta(days=60),
                ),
                Member(user_id=2, chat_id=-100, warn_count=1, last_warn_date=now),
            ]
        )
    reset_count = reset_expired_warns()
    assert reset_count == 1
    with session_scope() as session:
        old = (
            session.query(Member)
            .filter(Member.user_id == 1, Member.chat_id == -100)
            .one()
        )
        recent = (
            session.query(Member)
            .filter(Member.user_id == 2, Member.chat_id == -100)
            .one()
        )
    assert old.warn_count == 0
    assert recent.warn_count == 1


def test_reset_expired_warns_ignores_members_without_warns():
    with session_scope() as session:
        session.add(Member(user_id=3, chat_id=-100, warn_count=0, last_warn_date=None))
    assert reset_expired_warns() == 0
