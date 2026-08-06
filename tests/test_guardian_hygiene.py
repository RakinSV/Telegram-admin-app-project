"""Служебная гигиена группы (F48): чистка служебных сообщений, ночной режим,
напоминание правил."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest

from guardian import settings_store
from guardian.config import invalidate_settings_cache
from guardian.handlers import hygiene

CHAT = -100999


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in (
        "DELETE_JOIN_LEAVE_MESSAGES", "DELETE_PIN_NOTIFICATIONS",
        "DELETE_SERVICE_MESSAGES", "NIGHT_MODE_ENABLED", "GUARDIAN_GROUP_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    # protected_chat_ids живёт в БД (галочка use_guardian на цели в админке
    # tg_repost), а НЕ в env — поэтому чат надо защитить именно так.
    settings_store.sync_protected_chat_ids([CHAT])
    invalidate_settings_cache()
    yield
    settings_store.sync_protected_chat_ids([])
    invalidate_settings_cache()


def _message(chat_id: int = CHAT, **fields) -> SimpleNamespace:
    """Сообщение с нужными служебными полями; остальные — None, как у aiogram."""
    base = dict.fromkeys(
        ("new_chat_members", "left_chat_member", "pinned_message",
         "new_chat_title", "new_chat_photo", "delete_chat_photo",
         "group_chat_created", "supergroup_chat_created", "channel_chat_created",
         "message_auto_delete_timer_changed", "video_chat_started",
         "video_chat_ended", "video_chat_participants_invited"),
    )
    base.update(fields)
    return SimpleNamespace(chat=SimpleNamespace(id=chat_id), message_id=1, **base)


def _bad_request(msg: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=SimpleNamespace(), message=msg)


# --- классификация служебных сообщений ---


def test_service_kind_detects_join_and_leave():
    assert hygiene._service_kind(_message(new_chat_members=[object()])) == "join_leave"
    assert hygiene._service_kind(_message(left_chat_member=object())) == "join_leave"


def test_service_kind_detects_pin_separately():
    """Закреп — отдельный род: иногда это единственный способ участнику
    узнать о закреплённом, и чистить его не всегда верно."""
    assert hygiene._service_kind(_message(pinned_message=object())) == "pinned"


def test_service_kind_none_for_regular_message():
    assert hygiene._service_kind(_message()) is None


# --- удаление ---


async def test_deletes_join_leave_when_enabled(monkeypatch):
    monkeypatch.setenv("DELETE_JOIN_LEAVE_MESSAGES", "true")
    invalidate_settings_cache()
    bot = AsyncMock()
    await hygiene.on_service_message(_message(new_chat_members=[object()]), bot)
    bot.delete_message.assert_awaited_once_with(CHAT, 1)


async def test_does_not_delete_when_disabled():
    bot = AsyncMock()
    await hygiene.on_service_message(_message(new_chat_members=[object()]), bot)
    bot.delete_message.assert_not_awaited()


async def test_never_touches_regular_messages(monkeypatch):
    """Ключевая защита: включённая чистка не должна глушить обычное общение."""
    monkeypatch.setenv("DELETE_JOIN_LEAVE_MESSAGES", "true")
    monkeypatch.setenv("DELETE_SERVICE_MESSAGES", "true")
    invalidate_settings_cache()
    bot = AsyncMock()
    await hygiene.on_service_message(_message(), bot)
    bot.delete_message.assert_not_awaited()


async def test_ignores_unprotected_chat(monkeypatch):
    monkeypatch.setenv("DELETE_JOIN_LEAVE_MESSAGES", "true")
    invalidate_settings_cache()
    bot = AsyncMock()
    await hygiene.on_service_message(_message(chat_id=-100000, new_chat_members=[object()]), bot)
    bot.delete_message.assert_not_awaited()


async def test_pin_setting_is_independent(monkeypatch):
    """Включённая чистка вступлений не должна сносить уведомления о закрепе."""
    monkeypatch.setenv("DELETE_JOIN_LEAVE_MESSAGES", "true")
    invalidate_settings_cache()
    bot = AsyncMock()
    await hygiene.on_service_message(_message(pinned_message=object()), bot)
    bot.delete_message.assert_not_awaited()


async def test_delete_failure_is_swallowed(monkeypatch):
    """Сообщение старше 48ч Bot API удалять не даёт — это не повод падать."""
    monkeypatch.setenv("DELETE_JOIN_LEAVE_MESSAGES", "true")
    invalidate_settings_cache()
    bot = AsyncMock()
    bot.delete_message.side_effect = _bad_request("message can't be deleted")
    await hygiene.on_service_message(_message(new_chat_members=[object()]), bot)


# --- ночной режим ---


@pytest.mark.parametrize(
    ("hour", "start", "end", "expected"),
    [
        (23, 23, 7, True), (2, 23, 7, True), (6, 23, 7, True),   # ночь через полночь
        (7, 23, 7, False), (12, 23, 7, False),                    # день
        (14, 13, 15, True), (16, 13, 15, False),                  # интервал внутри суток
        (5, 0, 0, False),                                         # start==end — выключено
    ],
)
def test_is_night_now_handles_midnight_wrap(hour, start, end, expected):
    assert hygiene.is_night_now(hour, start, end) is expected


async def test_set_night_mode_closes_chat():
    bot = AsyncMock()
    assert await hygiene.set_night_mode(bot, CHAT, closed=True) is True
    perms = bot.set_chat_permissions.await_args.args[1]
    assert perms.can_send_messages is False


async def test_set_night_mode_opens_chat():
    bot = AsyncMock()
    assert await hygiene.set_night_mode(bot, CHAT, closed=False) is True
    perms = bot.set_chat_permissions.await_args.args[1]
    assert perms.can_send_messages is True


async def test_set_night_mode_reports_failure():
    """Нет прав у бота — возвращаем False, чтобы джоба не записала ложное
    состояние «закрыто» и утром не пропустила открытие."""
    bot = AsyncMock()
    bot.set_chat_permissions.side_effect = _bad_request("not enough rights")
    assert await hygiene.set_night_mode(bot, CHAT, closed=True) is False


# --- напоминание правил ---


async def test_rules_reminder_sends_text():
    bot = AsyncMock()
    assert await hygiene.send_rules_reminder(bot, CHAT, "Правила: не спамить") is True
    assert bot.send_message.await_args.args[1] == "Правила: не спамить"


async def test_rules_reminder_skips_empty_text():
    """Лучше молчать, чем слать пустое напоминание."""
    bot = AsyncMock()
    assert await hygiene.send_rules_reminder(bot, CHAT, "   ") is False
    bot.send_message.assert_not_awaited()
