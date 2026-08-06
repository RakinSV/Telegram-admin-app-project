"""Каркас бота Engage (пункт 8.3): конфиг, токен из шифрованной БД,
разбор deep-link — фундамент для F42 (рефералы), F44 (конкурсы), F47 (предложка).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from engage.config import get_engage_settings
from engage.handlers import start
from tg_repost.webui import settings_store


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("ENGAGE_BOT_TOKEN", raising=False)
    yield


# --- разбор deep-link ---


@pytest.mark.parametrize(
    ("payload", "kind", "value"),
    [
        ("ref_12345", start.PAYLOAD_REFERRAL, "12345"),
        ("contest_7", start.PAYLOAD_CONTEST, "7"),
        ("suggest", start.PAYLOAD_SUGGEST, ""),
        # Значение с подчёркиваниями: делим по ПЕРВОМУ, остальное — payload.
        ("ref_abc_def", start.PAYLOAD_REFERRAL, "abc_def"),
    ],
)
def test_parse_payload(payload, kind, value):
    link = start.parse_payload(payload)
    assert link is not None
    assert link.kind == kind
    assert link.value == value


def test_parse_payload_none_for_plain_start():
    """Обычный /start без ссылки — не ошибка, просто нет payload."""
    assert start.parse_payload(None) is None
    assert start.parse_payload("") is None


async def test_start_answers_without_payload():
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1), answer=AsyncMock(),
    )
    await start.on_start(message, SimpleNamespace(args=None), AsyncMock())
    message.answer.assert_awaited_once()


async def test_start_answers_on_unknown_payload():
    """Ссылку могли скопировать из старого поста — молчать нельзя."""
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1), answer=AsyncMock(),
    )
    await start.on_start(message, SimpleNamespace(args="whoknows_1"), AsyncMock())
    message.answer.assert_awaited_once()


async def test_start_survives_missing_from_user():
    """У сообщений из каналов from_user может отсутствовать — не падаем."""
    message = SimpleNamespace(from_user=None, answer=AsyncMock())
    await start.on_start(message, SimpleNamespace(args="ref_5"), AsyncMock())
    message.answer.assert_awaited_once()


# --- конфиг и токен ---


def test_not_configured_without_token():
    assert get_engage_settings().is_configured is False


def test_token_from_env(monkeypatch):
    monkeypatch.setenv("ENGAGE_BOT_TOKEN", "123:FROM-ENV")
    assert get_engage_settings().engage_bot_token == "123:FROM-ENV"


def test_token_from_encrypted_db_overrides_env(monkeypatch):
    """Токен задаётся в веб-админке (шифрованная таблица `secrets`), а не
    правкой .env на сервере — тот же приём, что у Guardian."""
    monkeypatch.setenv("ENGAGE_BOT_TOKEN", "123:FROM-ENV")
    settings_store.set_secret("engage_bot_token", "456:FROM-DB")
    try:
        assert get_engage_settings().engage_bot_token == "456:FROM-DB"
    finally:
        settings_store.clear_secret("engage_bot_token")


def test_engage_token_is_a_known_secret():
    """Регресс: секрет должен быть объявлен, иначе set_secret его отвергнет."""
    from tg_repost.config import SECRET_FIELD_NAMES

    assert "engage_bot_token" in SECRET_FIELD_NAMES
