"""Тесты пайплайна `handlers/messages.py::on_message` — режимы спам-фильтра
(G03/G09/G10) и связка с daily_stats (счётчик AI-вызовов)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from guardian.config import invalidate_settings_cache
from guardian.db.models import BotConfig, DailyStats, Member, ModerationLog, TrustedUser
from guardian.db.session import session_scope
from guardian.filters import ai_filter
from guardian.handlers import messages as messages_handlers

CHAT_ID = -100123  # совпадает с GUARDIAN_GROUP_ID из tests/conftest.py


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    with session_scope() as session:
        session.query(TrustedUser).delete()
        session.query(Member).delete()
        session.query(ModerationLog).delete()
        session.query(DailyStats).delete()
        session.query(BotConfig).delete()
    invalidate_settings_cache()
    messages_handlers.keyword_filter._words = set()
    # flood_filter — тоже синглтон на процесс, копит состояние по user_id
    # между тестами (все тесты этого файла по умолчанию используют
    # user_id=555) — без сброса N-й по счёту тест в файле ложно попадал бы
    # под срабатывание антифлуда и выходил из on_message раньше, чем дойдёт
    # до проверяемой ветки (найдено эмпирически: 6-й тест в файле падал).
    messages_handlers.flood_filter._timestamps.clear()
    messages_handlers.flood_filter._last_text.clear()
    yield
    with session_scope() as session:
        session.query(TrustedUser).delete()
        session.query(Member).delete()
        session.query(ModerationLog).delete()
        session.query(DailyStats).delete()
        session.query(BotConfig).delete()
    invalidate_settings_cache()


def _message(text: str, user_id: int = 555, forward_origin=None) -> SimpleNamespace:
    msg = AsyncMock()
    msg.from_user = SimpleNamespace(id=user_id, is_bot=False)
    msg.chat = SimpleNamespace(id=CHAT_ID, type="group")
    msg.text = text
    msg.caption = None
    msg.forward_origin = forward_origin
    msg.message_id = 1
    return msg


async def test_keywords_mode_never_calls_ai(monkeypatch):
    from guardian import settings_store

    settings_store.save_setting("spam_mode", "keywords", "str")
    ai_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(ai_filter, "classify", ai_mock)

    bot = AsyncMock()
    await messages_handlers.on_message(_message("обычное сообщение без ничего подозрительного"), bot)

    ai_mock.assert_not_awaited()


async def test_ai_mode_calls_ai_on_every_message(monkeypatch):
    from guardian import settings_store

    settings_store.save_setting("spam_mode", "ai", "str")
    result = ai_filter.ClassificationResult(is_spam=False, reason="", confidence=0.1, cost_usd=0.001)
    ai_mock = AsyncMock(return_value=result)
    monkeypatch.setattr(ai_filter, "classify", ai_mock)

    bot = AsyncMock()
    await messages_handlers.on_message(_message("любое сообщение"), bot)

    ai_mock.assert_awaited_once()
    with session_scope() as session:
        row = session.query(DailyStats).filter(DailyStats.chat_id == CHAT_ID).one()
        assert row.ai_calls == 1


async def test_ai_mode_deletes_when_spam_and_confident(monkeypatch):
    from guardian import settings_store

    settings_store.save_setting("spam_mode", "ai", "str")
    settings_store.save_setting("ai_spam_confidence_threshold", 0.75, "float")
    result = ai_filter.ClassificationResult(
        is_spam=True, reason="реклама", confidence=0.9, cost_usd=0.001
    )
    monkeypatch.setattr(ai_filter, "classify", AsyncMock(return_value=result))

    bot = AsyncMock()
    message = _message("купи крипту")
    await messages_handlers.on_message(message, bot)

    message.delete.assert_awaited_once()
    with session_scope() as session:
        log = session.query(ModerationLog).filter(ModerationLog.action == "delete_msg").one()
        assert "AI: реклама" in log.reason


async def test_ai_mode_does_not_delete_when_low_confidence(monkeypatch):
    from guardian import settings_store

    settings_store.save_setting("spam_mode", "ai", "str")
    settings_store.save_setting("ai_spam_confidence_threshold", 0.9, "float")
    result = ai_filter.ClassificationResult(
        is_spam=True, reason="возможно реклама", confidence=0.5, cost_usd=0.001
    )
    monkeypatch.setattr(ai_filter, "classify", AsyncMock(return_value=result))

    bot = AsyncMock()
    message = _message("сомнительное сообщение")
    await messages_handlers.on_message(message, bot)

    message.delete.assert_not_awaited()


async def test_hybrid_mode_skips_ai_when_not_suspicious(monkeypatch):
    from guardian import settings_store

    settings_store.save_setting("spam_mode", "hybrid", "str")
    ai_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(ai_filter, "classify", ai_mock)

    bot = AsyncMock()
    await messages_handlers.on_message(_message("привет как дела совсем обычное сообщение"), bot)

    ai_mock.assert_not_awaited()


async def test_hybrid_mode_calls_ai_when_suspicious(monkeypatch):
    from guardian import settings_store

    settings_store.save_setting("spam_mode", "hybrid", "str")
    result = ai_filter.ClassificationResult(is_spam=False, reason="", confidence=0.1, cost_usd=0.0)
    ai_mock = AsyncMock(return_value=result)
    monkeypatch.setattr(ai_filter, "classify", ai_mock)

    bot = AsyncMock()
    # 2 признака: цена + "пиши в личку" -> должно уйти в AI
    await messages_handlers.on_message(_message("Продам за 500$, пиши в личку"), bot)

    ai_mock.assert_awaited_once()


async def test_strict_mode_deletes_bad_link():
    from guardian import settings_store

    settings_store.save_setting("strict_mode", True, "bool")
    settings_store.save_setting("spam_mode", "keywords", "str")

    bot = AsyncMock()
    message = _message("заходи на https://spam-example.com прямо сейчас")
    await messages_handlers.on_message(message, bot)

    message.delete.assert_awaited_once()
    with session_scope() as session:
        assert session.query(ModerationLog).filter(ModerationLog.action == "delete_msg").count() == 1


async def test_soft_mode_only_logs_bad_link_without_deleting():
    """G16: в soft-режиме ссылки только логируются — не удаляются, варн не
    выдаётся (см. GUARDIAN_FEATURES.md G16)."""
    from guardian import settings_store

    settings_store.save_setting("strict_mode", False, "bool")
    settings_store.save_setting("spam_mode", "keywords", "str")

    bot = AsyncMock()
    message = _message("заходи на https://spam-example.com прямо сейчас")
    await messages_handlers.on_message(message, bot)

    message.delete.assert_not_awaited()
    with session_scope() as session:
        assert session.query(ModerationLog).filter(ModerationLog.action == "delete_msg").count() == 0
        flagged = session.query(ModerationLog).filter(ModerationLog.action == "link_flagged").one()
        assert "spam-example.com" in flagged.reason


async def test_trusted_user_bypasses_ai_entirely(monkeypatch):
    from guardian import settings_store

    settings_store.save_setting("spam_mode", "ai", "str")
    with session_scope() as session:
        session.add(TrustedUser(user_id=555, chat_id=CHAT_ID, added_by="test"))
    ai_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(ai_filter, "classify", ai_mock)

    bot = AsyncMock()
    await messages_handlers.on_message(_message("что угодно, хоть спам"), bot)

    ai_mock.assert_not_awaited()
