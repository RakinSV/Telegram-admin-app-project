"""Тесты антирейда (G14) — независимо на каждую защищаемую группу (F28)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from guardian import settings_store
from guardian.config import invalidate_settings_cache
from guardian.db.models import BotConfig, Member, ModerationLog
from guardian.db.session import session_scope
from guardian.handlers import admin as admin_module
from guardian.services import raid_detector

CHAT_ID = -100123
OTHER_CHAT_ID = -100456


@pytest.fixture(autouse=True)
def _isolated():
    with session_scope() as session:
        session.query(Member).delete()
        session.query(ModerationLog).delete()
        session.query(BotConfig).delete()
    invalidate_settings_cache()
    settings_store.sync_protected_chat_ids([CHAT_ID])
    raid_detector._states.clear()
    yield
    with session_scope() as session:
        session.query(Member).delete()
        session.query(ModerationLog).delete()
        session.query(BotConfig).delete()
    invalidate_settings_cache()
    raid_detector._states.clear()


_next_user_id = [1000]


def _join_members(count: int, minutes_ago: int = 0, chat_id: int = CHAT_ID) -> None:
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        for _ in range(count):
            user_id = _next_user_id[0]
            _next_user_id[0] += 1
            session.add(
                Member(
                    user_id=user_id,
                    chat_id=chat_id,
                    join_date=now - timedelta(minutes=minutes_ago),
                )
            )


async def test_no_raid_below_threshold(monkeypatch):
    settings_store.save_setting("raid_join_threshold", 5, "int")
    settings_store.save_setting("raid_join_window_minutes", 2, "int")
    _join_members(3)

    bot = AsyncMock()
    await raid_detector.check_raid(bot)

    assert raid_detector.is_raid_active(CHAT_ID) is False
    bot.set_chat_permissions.assert_not_awaited()


async def test_raid_triggered_above_threshold(monkeypatch):
    settings_store.save_setting("raid_join_threshold", 3, "int")
    settings_store.save_setting("raid_join_window_minutes", 2, "int")
    settings_store.save_setting("guardian_log_channel_id", 0, "int")  # без канала — просто без уведомления
    _join_members(5)

    bot = AsyncMock()
    bot.get_chat = AsyncMock(return_value=SimpleNamespace(permissions=None))
    await raid_detector.check_raid(bot)

    assert raid_detector.is_raid_active(CHAT_ID) is True
    bot.set_chat_permissions.assert_awaited_once()
    with session_scope() as session:
        log = session.query(ModerationLog).filter(ModerationLog.action == "raid_detected").one()
        assert "5 участников" in log.reason


async def test_raid_saves_current_permissions_before_freezing():
    settings_store.save_setting("raid_join_threshold", 1, "int")
    settings_store.save_setting("raid_join_window_minutes", 2, "int")
    _join_members(3)

    original_permissions = SimpleNamespace(can_send_messages=True)
    bot = AsyncMock()
    bot.get_chat = AsyncMock(return_value=SimpleNamespace(permissions=original_permissions))
    await raid_detector.check_raid(bot)

    assert raid_detector._get_state(CHAT_ID).saved_permissions is original_permissions


async def test_raid_does_not_retrigger_while_active():
    settings_store.save_setting("raid_join_threshold", 1, "int")
    settings_store.save_setting("raid_join_window_minutes", 2, "int")
    settings_store.save_setting("raid_cooldown_minutes", 10, "int")
    _join_members(5)

    bot = AsyncMock()
    bot.get_chat = AsyncMock(return_value=SimpleNamespace(permissions=None))
    await raid_detector.check_raid(bot)
    bot.set_chat_permissions.reset_mock()

    # Второй тик — рейд уже активен, новых вступлений нет за окно кулдауна,
    # так что перейдёт в ветку восстановления, а не повторной заморозки.
    await raid_detector.check_raid(bot)

    # set_chat_permissions вызван (восстановление), но НЕ повторная заморозка —
    # проверяем через отсутствие повторной ModerationLog(raid_detected).
    with session_scope() as session:
        count = session.query(ModerationLog).filter(ModerationLog.action == "raid_detected").count()
        assert count == 1


async def test_raid_auto_restores_after_cooldown_with_no_new_joins():
    settings_store.save_setting("raid_join_threshold", 1, "int")
    settings_store.save_setting("raid_join_window_minutes", 2, "int")
    settings_store.save_setting("raid_cooldown_minutes", 5, "int")
    _join_members(3)

    bot = AsyncMock()
    bot.get_chat = AsyncMock(return_value=SimpleNamespace(permissions=None))
    await raid_detector.check_raid(bot)
    assert raid_detector.is_raid_active(CHAT_ID) is True

    # Симулируем, что прошло 10 минут (кулдаун 5) без реального sleep —
    # "сейчас" для второй проверки сдвинуто вперёд через параметр `now`.
    later = datetime.now(timezone.utc) + timedelta(minutes=10)
    await raid_detector.check_raid(bot, now=later)

    assert raid_detector.is_raid_active(CHAT_ID) is False
    with session_scope() as session:
        assert session.query(ModerationLog).filter(ModerationLog.action == "raid_end").count() == 1


async def test_raid_stays_active_if_joins_continue_within_cooldown():
    settings_store.save_setting("raid_join_threshold", 1, "int")
    settings_store.save_setting("raid_join_window_minutes", 2, "int")
    settings_store.save_setting("raid_cooldown_minutes", 30, "int")
    _join_members(3)

    bot = AsyncMock()
    bot.get_chat = AsyncMock(return_value=SimpleNamespace(permissions=None))
    await raid_detector.check_raid(bot)
    assert raid_detector.is_raid_active(CHAT_ID) is True

    # +10 минут (кулдаун 30) — ещё кто-то вступил ПРЯМО СЕЙЧАС (в этот
    # сдвинутый момент), кулдаун не истёк.
    later = datetime.now(timezone.utc) + timedelta(minutes=10)
    with session_scope() as session:
        session.add(Member(user_id=_next_user_id[0], chat_id=CHAT_ID, join_date=later))
        _next_user_id[0] += 1
    await raid_detector.check_raid(bot, now=later)

    assert raid_detector.is_raid_active(CHAT_ID) is True


async def test_raid_independent_per_chat():
    """F28: рейд в одной защищаемой группе не должен влиять на другую —
    раньше состояние было одно глобальное на единственную группу."""
    settings_store.save_setting("raid_join_threshold", 2, "int")
    settings_store.save_setting("raid_join_window_minutes", 2, "int")
    settings_store.sync_protected_chat_ids([CHAT_ID, OTHER_CHAT_ID])
    _join_members(5, chat_id=CHAT_ID)
    _join_members(1, chat_id=OTHER_CHAT_ID)  # ниже порога

    bot = AsyncMock()
    bot.get_chat = AsyncMock(return_value=SimpleNamespace(permissions=None))
    await raid_detector.check_raid(bot)

    assert raid_detector.is_raid_active(CHAT_ID) is True
    assert raid_detector.is_raid_active(OTHER_CHAT_ID) is False


async def test_manual_unfreeze_callback_restores_permissions():
    admin_module._admin_cache.clear()
    raid_detector._get_state(CHAT_ID).active = True
    raid_detector._get_state(CHAT_ID).saved_permissions = SimpleNamespace(can_send_messages=True)

    callback = AsyncMock()
    callback.data = f"raid:unfreeze:{CHAT_ID}"
    callback.from_user = SimpleNamespace(id=111)
    callback.message = SimpleNamespace(
        chat=SimpleNamespace(id=CHAT_ID), text="🚨 Рейд-атака!", edit_text=AsyncMock()
    )

    bot = AsyncMock()
    bot.get_chat_administrators = AsyncMock(
        return_value=[SimpleNamespace(user=SimpleNamespace(id=111))]
    )

    await raid_detector.on_raid_callback(callback, bot)

    assert raid_detector.is_raid_active(CHAT_ID) is False
    bot.set_chat_permissions.assert_awaited_once()


async def test_raid_callback_denied_for_non_admin():
    admin_module._admin_cache.clear()
    raid_detector._get_state(CHAT_ID).active = True

    callback = AsyncMock()
    callback.data = f"raid:unfreeze:{CHAT_ID}"
    callback.from_user = SimpleNamespace(id=999)
    callback.message = SimpleNamespace(
        chat=SimpleNamespace(id=CHAT_ID), text="🚨 Рейд-атака!", edit_text=AsyncMock()
    )

    bot = AsyncMock()
    bot.get_chat_administrators = AsyncMock(return_value=[])

    await raid_detector.on_raid_callback(callback, bot)

    assert raid_detector.is_raid_active(CHAT_ID) is True  # не тронуто
    bot.set_chat_permissions.assert_not_awaited()


async def test_raid_callback_checks_admin_of_group_not_of_log_channel():
    """Регрессия security-ревью: кнопки шлются в `guardian_log_channel_id`
    (независимо настраиваемый чат — может отличаться от группы, см. .env.example),
    поэтому проверка админства ДОЛЖНА идти по chat_id ИЗ КНОПКИ, а не по
    чату, откуда пришёл callback (в старой версии — уязвимость: админ
    лог-канала мог разморозить чужую группу)."""
    admin_module._admin_cache.clear()
    raid_detector._get_state(CHAT_ID).active = True
    LOG_CHANNEL_ID = -100999

    callback = AsyncMock()
    callback.data = f"raid:unfreeze:{CHAT_ID}"
    callback.from_user = SimpleNamespace(id=111)
    callback.message = SimpleNamespace(
        chat=SimpleNamespace(id=LOG_CHANNEL_ID), text="🚨 Рейд-атака!", edit_text=AsyncMock()
    )

    bot = AsyncMock()

    async def _get_admins(chat_id):
        if chat_id == LOG_CHANNEL_ID:
            return [SimpleNamespace(user=SimpleNamespace(id=111))]  # 111 — админ лог-канала
        return []  # но НЕ админ группы (CHAT_ID)

    bot.get_chat_administrators = AsyncMock(side_effect=_get_admins)

    await raid_detector.on_raid_callback(callback, bot)

    assert raid_detector.is_raid_active(CHAT_ID) is True  # не разморожено
    bot.set_chat_permissions.assert_not_awaited()


async def test_raid_callback_unfreezes_only_the_encoded_chat():
    """F28: разморозка кнопкой из уведомления об одной группе не должна
    задевать состояние другой защищаемой группы."""
    admin_module._admin_cache.clear()
    settings_store.sync_protected_chat_ids([CHAT_ID, OTHER_CHAT_ID])
    raid_detector._get_state(CHAT_ID).active = True
    raid_detector._get_state(OTHER_CHAT_ID).active = True

    callback = AsyncMock()
    callback.data = f"raid:unfreeze:{CHAT_ID}"
    callback.from_user = SimpleNamespace(id=111)
    callback.message = SimpleNamespace(
        chat=SimpleNamespace(id=CHAT_ID), text="🚨 Рейд-атака!", edit_text=AsyncMock()
    )

    bot = AsyncMock()
    bot.get_chat_administrators = AsyncMock(
        return_value=[SimpleNamespace(user=SimpleNamespace(id=111))]
    )

    await raid_detector.on_raid_callback(callback, bot)

    assert raid_detector.is_raid_active(CHAT_ID) is False
    assert raid_detector.is_raid_active(OTHER_CHAT_ID) is True
