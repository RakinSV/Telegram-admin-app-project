"""Тесты MTProto/SOCKS5-прокси: Telethon (build_client/build_extra_clients),
Bot API репост-бота (moderation_bot.build_application) и Bot API Guardian
(config.py::bot_api_proxy_url, используется в bot.py::main)."""

from __future__ import annotations

from pathlib import Path

import pytest
from aiogram.client.session.aiohttp import AiohttpSession
from dotenv import dotenv_values
from telethon.network.connection.tcpmtproxy import ConnectionTcpMTProxyRandomizedIntermediate

from guardian.config import (
    GuardianSettings,
    get_guardian_settings,
    invalidate_settings_cache as guardian_invalidate_settings_cache,
)
from tg_repost.config import invalidate_settings_cache
from tg_repost.telegram.listener import build_client
from tg_repost.telegram.moderation_bot import build_application

_ENV_EXAMPLE = Path(__file__).parent.parent / ".env.example"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    for key in (
        "MTPROTO_PROXY_HOST", "MTPROTO_PROXY_PORT", "MTPROTO_PROXY_SECRET",
        "BOT_API_PROXY_URL", "GUARDIAN_BOT_API_PROXY_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    invalidate_settings_cache()
    guardian_invalidate_settings_cache()
    yield
    invalidate_settings_cache()
    guardian_invalidate_settings_cache()


async def test_build_client_without_proxy_uses_default_connection():
    # async — не просто стиль: TelegramClient.__init__ дёргает asyncio.
    # get_running_loop() внутри (см. telethon/client/telegrambaseclient.py::
    # loop), в sync-тесте после нескольких async-тестов до него в общем
    # прогоне в потоке уже нет текущего event loop (Python 3.12) — падает
    # RuntimeError, хотя сам build_client() с сетью не работает.
    client = build_client()
    assert client._proxy is None


async def test_build_client_with_mtproto_proxy_configured(monkeypatch):
    monkeypatch.setenv("MTPROTO_PROXY_HOST", "1.2.3.4")
    monkeypatch.setenv("MTPROTO_PROXY_PORT", "443")
    monkeypatch.setenv("MTPROTO_PROXY_SECRET", "deadbeefdeadbeefdeadbeefdeadbeef")

    client = build_client()

    assert client._proxy == ("1.2.3.4", 443, "deadbeefdeadbeefdeadbeefdeadbeef")
    assert client._connection is ConnectionTcpMTProxyRandomizedIntermediate


def test_build_application_without_proxy_does_not_crash():
    build_application()  # baseline — не должно падать без прокси


def test_build_application_with_socks5_proxy_does_not_crash(monkeypatch):
    # Bot API — SOCKS5, не MTProto (см. docstring build_application) — без
    # httpx[socks] (socksio) эта строка падает ImportError при первом
    # реальном запросе; здесь важно, что САМА сборка Application не падает.
    monkeypatch.setenv("BOT_API_PROXY_URL", "socks5://user:pass@1.2.3.4:1080")
    build_application()


def test_guardian_bot_api_proxy_url_defaults_empty():
    assert get_guardian_settings().bot_api_proxy_url == ""


def test_guardian_bot_api_proxy_url_read_from_env(monkeypatch):
    monkeypatch.setenv("GUARDIAN_BOT_API_PROXY_URL", "socks5://user:pass@1.2.3.4:1080")
    assert get_guardian_settings().bot_api_proxy_url == "socks5://user:pass@1.2.3.4:1080"


def test_guardian_aiohttp_session_picks_up_proxy_without_crash(monkeypatch):
    # То же самое, что делает bot.py::main() — без aiohttp_socks эта строка
    # упала бы ImportError при первом реальном запросе, важно что сборка
    # session сама по себе не падает.
    monkeypatch.setenv("GUARDIAN_BOT_API_PROXY_URL", "socks5://user:pass@1.2.3.4:1080")
    settings = get_guardian_settings()
    session = AiohttpSession(proxy=settings.bot_api_proxy_url)
    assert session._proxy == "socks5://user:pass@1.2.3.4:1080"


def test_guardian_settings_constructs_with_real_env_example_values(monkeypatch):
    # Тот же приём, что tests/test_config.py делает для tg_repost.Settings —
    # оба реальных прод-бага (NoDecode, MTPROTO_PROXY_PORT="") нашлись именно
    # прямым прогоном против файла. GuardianSettings читает тот же .env.
    values = dotenv_values(_ENV_EXAMPLE)
    for key, value in values.items():
        monkeypatch.setenv(key, value or "")
    GuardianSettings()  # type: ignore[call-arg]  # не должно бросить ValidationError


def test_build_application_with_malformed_proxy_url_falls_back_without_crash(monkeypatch, caplog):
    # Регрессия (security-ревью): PTB парсит URL прокси ИМЕННО в .build()
    # (не лениво при первом запросе) — битый BOT_API_PROXY_URL раньше ронял
    # необработанным ValueError весь процесс main.py (веб-панель обязана
    # подниматься ВСЕГДА, даже без рабочего Telegram-конфига).
    monkeypatch.setenv("BOT_API_PROXY_URL", "not-a-valid-proxy-url")
    application = build_application()
    assert application is not None
    assert "BOT_API_PROXY_URL" in caplog.text


def test_guardian_aiohttp_session_with_malformed_proxy_url_raises_value_error():
    # bot.py::main() ловит именно этот ValueError и логирует понятную
    # ошибку вместо падения процесса (см. регресс на ту же находку выше).
    with pytest.raises(ValueError):
        AiohttpSession(proxy="not-a-valid-proxy-url")
