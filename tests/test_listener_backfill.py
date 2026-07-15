"""Тесты F02-доп: `listener.backfill_source` — разовый сбор упущенной
истории источника через тот же пайплайн, что и живой поток (F02→F03→F04).

Жалоба пользователя: live-слушатель ловит только сообщения, вышедшие ПОСЛЕ
того, как Telegram начал слать апдейты этому аккаунту (обычно — после
подписки) — старые посты сами по себе не появляются. `backfill_source`
тянет последние N сообщений через `client.iter_messages()` и прогоняет их
через `_process_message` (общий с `_handle_new_message`) вручную.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tg_repost import sources_repo
from tg_repost.db.models import Post, Source
from tg_repost.db.session import session_scope
from tg_repost.telegram import listener


class _FakeChat:
    def __init__(self, chat_id: int, username: str) -> None:
        self.id = chat_id
        self.username = username


class _FakeMessage:
    def __init__(self, msg_id: int, text: str, media: object = None) -> None:
        self.id = msg_id
        self.message = text
        self.media = media


def _fake_client(chat: _FakeChat, messages: list[_FakeMessage]) -> AsyncMock:
    """AsyncMock Telethon-клиента: `get_entity` отдаёт `chat`, `iter_messages`
    — асинхронный генератор по `messages` (Telethon отдаёт от новых к
    старым — тестовые списки ниже уже в этом порядке, как настоящий API)."""
    client = AsyncMock()
    client.get_entity = AsyncMock(return_value=chat)

    async def _iter_messages(entity, limit):  # noqa: ARG001
        for m in messages:
            yield m

    client.iter_messages = _iter_messages
    return client


@pytest.fixture(autouse=True)
def _no_jitter(monkeypatch):
    """F17-джиттер тут не нужен — иначе тест реально спит по 0.5-3с на сообщение."""
    monkeypatch.setattr(listener, "jitter_sleep", AsyncMock(return_value=None))


@pytest.fixture(autouse=True)
def _clean_tables():
    with session_scope() as session:
        session.query(Post).delete()
        session.query(Source).delete()
    yield


@pytest.mark.asyncio
async def test_backfill_source_processes_all_messages():
    source, _ = sources_repo.add_source("@testchan")
    chat = _FakeChat(chat_id=555, username="testchan")
    # Telethon iter_messages без reverse отдаёт от новых к старым.
    messages = [_FakeMessage(3, "third"), _FakeMessage(2, "second"), _FakeMessage(1, "first")]
    client = _fake_client(chat, messages)

    count = await listener.backfill_source(client, source, limit=10)

    assert count == 3
    with session_scope() as session:
        posts = session.query(Post).order_by(Post.source_message_id).all()
    assert [p.source_message_id for p in posts] == [1, 2, 3]


@pytest.mark.asyncio
async def test_backfill_source_processes_oldest_first(monkeypatch):
    """Сообщения должны дойти до `_process_message` в хронологическом
    порядке (старые → новые), а не в порядке выдачи Telethon (новые →
    старые)."""
    source, _ = sources_repo.add_source("@orderchan")
    chat = _FakeChat(chat_id=777, username="orderchan")
    messages = [_FakeMessage(30, "c"), _FakeMessage(20, "b"), _FakeMessage(10, "a")]
    client = _fake_client(chat, messages)

    processed_order: list[int] = []
    original = listener._process_message

    async def _spy(client_, chat_, message_):
        processed_order.append(message_.id)
        await original(client_, chat_, message_)

    monkeypatch.setattr(listener, "_process_message", _spy)
    await listener.backfill_source(client, source, limit=10)

    assert processed_order == [10, 20, 30]


@pytest.mark.asyncio
async def test_backfill_source_respects_filter_and_dedup():
    """Отфильтрованные/дублирующиеся сообщения не должны создавать
    отдельные посты со статусом NEW — тот же пайплайн F03/F04, что и live."""
    source, _ = sources_repo.add_source("@filterchan")
    chat = _FakeChat(chat_id=999, username="filterchan")
    messages = [
        _FakeMessage(2, "hello world"),
        _FakeMessage(1, "hello world"),  # точный дубль текста
    ]
    client = _fake_client(chat, messages)

    count = await listener.backfill_source(client, source, limit=10)

    assert count == 2  # оба дошли до _process_message...
    with session_scope() as session:
        statuses = [p.status.value for p in session.query(Post).order_by(Post.source_message_id).all()]
    # ...но второй по хронологии (msg_id=2) должен получить статус DUPLICATE.
    assert statuses == ["new", "duplicate"]


@pytest.mark.asyncio
async def test_backfill_source_unknown_source_username_still_calls_get_entity():
    """`backfill_source` резолвит entity по `source.channel_username`
    (не по BD channel_id — тот может быть ещё не заполнен для новых
    источников, см. отчёт пользователя channel_id=None)."""
    source, _ = sources_repo.add_source("@brandnew")
    assert source.channel_id is None
    chat = _FakeChat(chat_id=111, username="brandnew")
    client = _fake_client(chat, [])

    await listener.backfill_source(client, source, limit=5)

    client.get_entity.assert_awaited_once_with("brandnew")
