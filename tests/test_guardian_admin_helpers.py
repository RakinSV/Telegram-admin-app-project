"""Тесты чистых хелперов guardian/handlers/admin.py (парсинг длительности,
резолв цели команды из reply/числового id, кэш списка админов)."""

import time
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from guardian.handlers import admin
from guardian.handlers.admin import (
    _MAX_MUTE_DURATION,
    _get_admin_ids,
    _parse_duration,
    _resolve_target,
)


def test_parse_duration_minutes():
    assert _parse_duration("30m") == timedelta(minutes=30)


def test_parse_duration_hours():
    assert _parse_duration("1h") == timedelta(hours=1)


def test_parse_duration_days():
    assert _parse_duration("2d") == timedelta(days=2)


def test_parse_duration_invalid_returns_none():
    assert _parse_duration("abc") is None
    assert _parse_duration("") is None
    assert _parse_duration("5x") is None


def test_parse_duration_clamped_to_max():
    assert _parse_duration("999999d") == _MAX_MUTE_DURATION


def _message_with_reply(user_id: int | None) -> SimpleNamespace:
    reply = SimpleNamespace(from_user=SimpleNamespace(id=user_id)) if user_id else None
    return SimpleNamespace(reply_to_message=reply)


def test_resolve_target_from_reply():
    message = _message_with_reply(12345)
    user_id, rest = _resolve_target(message, "причина текст")
    assert user_id == 12345
    assert rest == "причина текст"


def test_resolve_target_from_numeric_arg_when_no_reply():
    message = _message_with_reply(None)
    user_id, rest = _resolve_target(message, "999888777 причина")
    assert user_id == 999888777
    assert rest == "причина"


def test_resolve_target_reply_takes_priority_over_arg():
    message = _message_with_reply(111)
    user_id, rest = _resolve_target(message, "999888777 причина")
    assert user_id == 111
    assert rest == "999888777 причина"


def test_resolve_target_none_when_no_reply_and_non_numeric_arg():
    message = _message_with_reply(None)
    user_id, rest = _resolve_target(message, "не число")
    assert user_id is None
    assert rest == "не число"


def test_resolve_target_negative_numeric_arg():
    message = _message_with_reply(None)
    user_id, _rest = _resolve_target(message, "-100123 причина")
    assert user_id == -100123


async def _admins_response(*user_ids: int) -> list[SimpleNamespace]:
    return [SimpleNamespace(user=SimpleNamespace(id=uid)) for uid in user_ids]


async def test_get_admin_ids_calls_api_once_then_uses_cache():
    admin._admin_cache.clear()
    bot = AsyncMock()
    bot.get_chat_administrators = AsyncMock(return_value=await _admins_response(1, 2))

    first = await _get_admin_ids(bot, chat_id=-100)
    second = await _get_admin_ids(bot, chat_id=-100)

    assert first == {1, 2}
    assert second == {1, 2}
    bot.get_chat_administrators.assert_awaited_once()  # второй вызов — из кэша


async def test_get_admin_ids_refreshes_after_ttl_expires():
    admin._admin_cache.clear()
    bot = AsyncMock()
    bot.get_chat_administrators = AsyncMock(return_value=await _admins_response(1))

    await _get_admin_ids(bot, chat_id=-100)
    # Искусственно "состариваем" запись вместо реального сна на TTL.
    ids, _ts = admin._admin_cache[-100]
    admin._admin_cache[-100] = (
        ids,
        time.monotonic() - admin._ADMIN_CACHE_TTL_SECONDS - 1,
    )

    await _get_admin_ids(bot, chat_id=-100)

    assert bot.get_chat_administrators.await_count == 2
