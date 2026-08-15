"""Обязательная подписка на канал (F61).

Это барьер на входе в общение, и почти все тесты здесь про то, чтобы он не
превратился в отталкивающий:

* сетевая ошибка НЕ должна перекрывать чат — fail-open, как у AI-фильтра;
* админ группы, забывший подписаться на свой же канал, должен писать
  свободно;
* напоминание не чаще раза в N минут, иначе пять сообщений подряд дадут
  пять уведомлений — спам от имени владельца.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest

from guardian.handlers import force_subscribe

CHAT = -100777222
CHANNEL = "@mychannel"
ADMIN = 1
MEMBER = 2


class _Settings:
    """Заглушка настроек Guardian.

    Патчим ФУНКЦИЮ, а не поля полученного объекта: `get_guardian_settings`
    перечитывает `bot_config` и может вернуть новый экземпляр, а соседние
    тесты дополнительно сбрасывают её кэш. Пропатченные поля тогда теряются,
    и тест зеленеет по отдельности, но падает в общем прогоне — ровно так
    это и всплыло.
    """

    def __init__(self, enabled: bool = True, channel: str = CHANNEL) -> None:
        self.force_subscribe_enabled = enabled
        self.force_subscribe_channel = channel


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr(
        force_subscribe, "get_guardian_settings", lambda: _Settings(), raising=True,
    )
    force_subscribe._last_reminder.clear()
    yield
    force_subscribe._last_reminder.clear()


def _bot(*, status: str = "member", raises: bool = False) -> AsyncMock:
    bot = AsyncMock()

    async def _get_member(channel, user_id):
        if raises:
            raise TelegramBadRequest(method=None, message="CHAT_ADMIN_REQUIRED")
        return SimpleNamespace(status=status)

    bot.get_chat_member = AsyncMock(side_effect=_get_member)
    bot.get_chat_administrators = AsyncMock(
        return_value=[SimpleNamespace(user=SimpleNamespace(id=ADMIN))]
    )
    bot.send_message = AsyncMock()
    return bot


def _message(user_id: int = MEMBER) -> SimpleNamespace:
    return SimpleNamespace(
        chat=SimpleNamespace(id=CHAT),
        from_user=SimpleNamespace(id=user_id, is_bot=False),
        delete=AsyncMock(),
    )


# --- основное поведение ---


async def test_subscribed_member_passes():
    message = _message()

    assert await force_subscribe.enforce(message, _bot(status="member")) is False
    message.delete.assert_not_awaited()


async def test_unsubscribed_message_is_deleted():
    message = _message()

    assert await force_subscribe.enforce(message, _bot(status="left")) is True
    message.delete.assert_awaited()


async def test_person_is_told_what_happened_and_given_a_link():
    """Молча удалённое сообщение выглядит как поломка чата, а не как правило.

    Новичок решит, что его забанили ни за что, и уйдёт — вместо того чтобы
    подписаться, ради чего всё и затевалось.
    """
    bot = _bot(status="left")

    await force_subscribe.enforce(_message(), bot)

    text = bot.send_message.await_args.args[1]
    assert "mychannel" in text
    assert "подпиш" in text.lower()


# --- не превращаемся в барьер ---


async def test_network_error_lets_message_through():
    """FAIL-OPEN. Перекрыть чат из-за сетевой ошибки хуже, чем пропустить
    одного неподписанного."""
    message = _message()

    assert await force_subscribe.enforce(message, _bot(raises=True)) is False
    message.delete.assert_not_awaited()


async def test_admin_is_exempt():
    """Владелец, забывший подписаться на свой же канал, не должен
    обнаружить, что не может писать в своей группе."""
    message = _message(user_id=ADMIN)

    assert await force_subscribe.enforce(message, _bot(status="left")) is False


async def test_reminder_is_throttled():
    """Пять сообщений подряд не должны дать пять уведомлений."""
    bot = _bot(status="left")

    for _ in range(4):
        await force_subscribe.enforce(_message(), bot)

    assert bot.send_message.await_count == 1


async def test_messages_still_deleted_while_reminder_is_silent():
    """Пауза касается ТОЛЬКО напоминания.

    Если бы она гасила и удаление, правило переставало бы работать на
    четыре минуты после первого срабатывания.
    """
    bot = _bot(status="left")
    first, second = _message(), _message()

    await force_subscribe.enforce(first, bot)
    await force_subscribe.enforce(second, bot)

    first.delete.assert_awaited()
    second.delete.assert_awaited()


# --- выключено и крайние случаи ---


async def test_disabled_does_nothing(monkeypatch):
    monkeypatch.setattr(
        force_subscribe, "get_guardian_settings",
        lambda: _Settings(enabled=False), raising=True,
    )
    message = _message()

    assert await force_subscribe.enforce(message, _bot(status="left")) is False


async def test_empty_channel_does_nothing(monkeypatch):
    """Включено, но канал не указан — проверять нечего, и падать незачем."""
    monkeypatch.setattr(
        force_subscribe, "get_guardian_settings",
        lambda: _Settings(channel="  "), raising=True,
    )
    message = _message()

    assert await force_subscribe.enforce(message, _bot(status="left")) is False


async def test_bots_are_ignored():
    message = _message()
    message.from_user.is_bot = True

    assert await force_subscribe.enforce(message, _bot(status="left")) is False


@pytest.mark.parametrize("status", ["creator", "administrator", "member"])
async def test_all_subscribed_statuses_pass(status):
    assert await force_subscribe.enforce(_message(), _bot(status=status)) is False


@pytest.mark.parametrize("status", ["left", "kicked", "restricted"])
async def test_non_member_statuses_are_blocked(status):
    assert await force_subscribe.enforce(_message(), _bot(status=status)) is True


async def test_unknown_result_is_none_not_false():
    """«Не знаем» и «не подписан» — разные вещи.

    Схлопни их в False, и сетевая ошибка начнёт удалять сообщения.
    """
    assert await force_subscribe.is_subscribed(_bot(raises=True), CHANNEL, MEMBER) is None
