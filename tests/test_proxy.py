"""Единый прокси-раздел (tg_repost/proxy.py): три типа (mtproto/socks5/http) ×
три галочки применения (telegram/rewrite/images), плюс интеграция с Telethon
(build_client / login-визард), Bot API репост-бота и Guardian.

Значения задаются через env (у полей алиасы PROXY_*), потому что Settings
конструируется из env, а не по именам полей (нет populate_by_name).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from aiogram.client.session.aiohttp import AiohttpSession
from dotenv import dotenv_values
from telethon.network.connection.tcpmtproxy import (
    ConnectionTcpMTProxyIntermediate,
    ConnectionTcpMTProxyRandomizedIntermediate,
)

from guardian.config import (
    GuardianSettings,
    get_guardian_settings,
)
from guardian.config import invalidate_settings_cache as guardian_invalidate_settings_cache
from tg_repost import proxy
from tg_repost.config import get_settings, invalidate_settings_cache
from tg_repost.telegram.listener import build_client
from tg_repost.telegram.moderation_bot import build_application
from tg_repost.tools.gen_session import start_telethon_login

_ENV_EXAMPLE = Path(__file__).parent.parent / ".env.example"

_PROXY_ENV = (
    "PROXY_MTPROTO_ENABLED", "PROXY_MTPROTO_ADDRESS", "PROXY_MTPROTO_SECRET",
    "PROXY_SOCKS5_ENABLED", "PROXY_SOCKS5_ADDRESS", "PROXY_SOCKS5_LOGIN", "PROXY_SOCKS5_PASSWORD",
    "PROXY_HTTP_ENABLED", "PROXY_HTTP_ADDRESS", "PROXY_HTTP_LOGIN", "PROXY_HTTP_PASSWORD",
    "PROXY_USE_FOR_TELEGRAM", "PROXY_USE_FOR_REWRITE", "PROXY_USE_FOR_IMAGES",
    # старые (должны игнорироваться новой логикой)
    "MTPROTO_PROXY_HOST", "MTPROTO_PROXY_PORT", "MTPROTO_PROXY_SECRET",
    "TELETHON_PROXY_URL", "BOT_API_PROXY_URL", "GUARDIAN_BOT_API_PROXY_URL",
)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    for key in _PROXY_ENV:
        monkeypatch.delenv(key, raising=False)
    invalidate_settings_cache()
    guardian_invalidate_settings_cache()
    yield
    invalidate_settings_cache()
    guardian_invalidate_settings_cache()


def _set(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))
    invalidate_settings_cache()
    return get_settings()


# --- разбор адреса ---


def test_split_host_port():
    assert proxy.split_host_port("1.2.3.4:1080") == ("1.2.3.4", 1080)
    assert proxy.split_host_port("proxy.example.com:8080") == ("proxy.example.com", 8080)
    assert proxy.split_host_port("[::1]:9050") == ("::1", 9050)


def test_split_host_port_rejects_bad_input():
    assert proxy.split_host_port("") is None
    assert proxy.split_host_port("нет-порта") is None
    assert proxy.split_host_port("host:notaport") is None
    assert proxy.split_host_port("host:") is None


# --- httpx-прокси (нейросети/бот) ---


def test_no_proxy_when_usage_flag_off(monkeypatch):
    s = _set(monkeypatch, PROXY_HTTP_ENABLED="true", PROXY_HTTP_ADDRESS="1.2.3.4:8080",
             PROXY_USE_FOR_REWRITE="false")
    assert proxy.httpx_proxy_url(s, "rewrite") is None


def test_http_proxy_for_rewrite(monkeypatch):
    s = _set(monkeypatch, PROXY_HTTP_ENABLED="true", PROXY_HTTP_ADDRESS="1.2.3.4:8080",
             PROXY_USE_FOR_REWRITE="true")
    assert proxy.httpx_proxy_url(s, "rewrite") == "http://1.2.3.4:8080"


def test_http_proxy_credentials_are_url_encoded(monkeypatch):
    s = _set(monkeypatch, PROXY_HTTP_ENABLED="true", PROXY_HTTP_ADDRESS="p:8080",
             PROXY_HTTP_LOGIN="user", PROXY_HTTP_PASSWORD="p@ss:w/rd",
             PROXY_USE_FOR_IMAGES="true")
    # спецсимволы пароля экранированы, иначе разбор URL сломался бы
    assert proxy.httpx_proxy_url(s, "images") == "http://user:p%40ss%3Aw%2Frd@p:8080"


def test_socks5_preferred_for_telegram(monkeypatch):
    s = _set(monkeypatch,
             PROXY_SOCKS5_ENABLED="true", PROXY_SOCKS5_ADDRESS="s:1080",
             PROXY_HTTP_ENABLED="true", PROXY_HTTP_ADDRESS="h:8080",
             PROXY_USE_FOR_TELEGRAM="true")
    assert proxy.httpx_proxy_url(s, "telegram") == "socks5://s:1080"


def test_http_preferred_for_llm(monkeypatch):
    s = _set(monkeypatch,
             PROXY_SOCKS5_ENABLED="true", PROXY_SOCKS5_ADDRESS="s:1080",
             PROXY_HTTP_ENABLED="true", PROXY_HTTP_ADDRESS="h:8080",
             PROXY_USE_FOR_REWRITE="true")
    assert proxy.httpx_proxy_url(s, "rewrite") == "http://h:8080"


def test_old_env_vars_are_ignored_by_new_logic(monkeypatch):
    """Старые TELETHON_PROXY_URL/BOT_API_PROXY_URL новой логикой не читаются —
    только новый раздел (иначе редизайн был бы иллюзией)."""
    s = _set(monkeypatch, TELETHON_PROXY_URL="socks5://old:1080",
             BOT_API_PROXY_URL="socks5://old:1080")
    assert proxy.httpx_proxy_url(s, "telegram") is None
    assert proxy.telethon_proxy_kwargs(s) == {}


# --- Telethon ---


def test_telethon_no_proxy_when_flag_off(monkeypatch):
    s = _set(monkeypatch, PROXY_SOCKS5_ENABLED="true", PROXY_SOCKS5_ADDRESS="s:1080")
    assert proxy.telethon_proxy_kwargs(s) == {}


async def test_build_client_without_proxy_uses_default_connection():
    # async: TelegramClient.__init__ дёргает asyncio.get_running_loop().
    client = build_client()
    assert client._proxy is None


async def test_build_client_socks5_tuple(monkeypatch):
    _set(monkeypatch, PROXY_SOCKS5_ENABLED="true",
         PROXY_SOCKS5_ADDRESS="1.2.3.4:1080", PROXY_SOCKS5_LOGIN="u",
         PROXY_SOCKS5_PASSWORD="p", PROXY_USE_FOR_TELEGRAM="true")
    client = build_client()
    assert client._proxy == ("socks5", "1.2.3.4", 1080, True, "u", "p")


async def test_build_client_socks5_without_creds(monkeypatch):
    _set(monkeypatch, PROXY_SOCKS5_ENABLED="true",
         PROXY_SOCKS5_ADDRESS="1.2.3.4:1080", PROXY_USE_FOR_TELEGRAM="true")
    client = build_client()
    assert client._proxy == ("socks5", "1.2.3.4", 1080, True)


async def test_build_client_mtproto_dd_secret_randomized(monkeypatch):
    # dd/ee-секрет ТРЕБУЕТ randomized intermediate (соглашение MTProxy).
    _set(monkeypatch, PROXY_MTPROTO_ENABLED="true", PROXY_MTPROTO_ADDRESS="1.2.3.4:443",
         PROXY_MTPROTO_SECRET="ddeadbeefdeadbeefdeadbeefdeadbeef",
         PROXY_USE_FOR_TELEGRAM="true")
    client = build_client()
    assert client._proxy == ("1.2.3.4", 443, "ddeadbeefdeadbeefdeadbeefdeadbeef")
    assert client._connection is ConnectionTcpMTProxyRandomizedIntermediate


async def test_build_client_mtproto_plain_secret_intermediate(monkeypatch):
    # Регрессия: обычный (не dd/ee) секрет требует ПРОСТОЙ intermediate,
    # иначе прокси рвёт соединение сразу после хендшейка.
    _set(monkeypatch, PROXY_MTPROTO_ENABLED="true", PROXY_MTPROTO_ADDRESS="1.2.3.4:443",
         PROXY_MTPROTO_SECRET="deadbeefdeadbeefdeadbeefdeadbeef",
         PROXY_USE_FOR_TELEGRAM="true")
    client = build_client()
    assert client._connection is ConnectionTcpMTProxyIntermediate


async def test_socks5_takes_precedence_over_mtproto(monkeypatch):
    _set(monkeypatch,
         PROXY_SOCKS5_ENABLED="true", PROXY_SOCKS5_ADDRESS="1.2.3.4:1080",
         PROXY_MTPROTO_ENABLED="true", PROXY_MTPROTO_ADDRESS="5.6.7.8:443",
         PROXY_MTPROTO_SECRET="ddeadbeefdeadbeefdeadbeefdeadbeef",
         PROXY_USE_FOR_TELEGRAM="true")
    client = build_client()
    assert client._proxy == ("socks5", "1.2.3.4", 1080, True)


async def test_build_client_bad_address_falls_back_direct(monkeypatch):
    _set(monkeypatch, PROXY_SOCKS5_ENABLED="true", PROXY_SOCKS5_ADDRESS="not-valid",
         PROXY_USE_FOR_TELEGRAM="true")
    client = build_client()
    assert client._proxy is None


async def test_start_telethon_login_applies_proxy(monkeypatch):
    # Регрессия: визард входа строил СВОЙ клиент в обход прокси, и самый
    # первый логин (которым добывается session string) шёл напрямую.
    _set(monkeypatch, PROXY_MTPROTO_ENABLED="true", PROXY_MTPROTO_ADDRESS="1.2.3.4:443",
         PROXY_MTPROTO_SECRET="ddeadbeefdeadbeefdeadbeefdeadbeef",
         PROXY_USE_FOR_TELEGRAM="true")
    from unittest.mock import AsyncMock

    monkeypatch.setattr("telethon.TelegramClient.connect", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "telethon.TelegramClient.send_code_request",
        AsyncMock(return_value=type("Sent", (), {"phone_code_hash": "hash"})()),
    )
    state = await start_telethon_login(api_id=1, api_hash="hash", phone="+10000000000")
    assert state.client._proxy == ("1.2.3.4", 443, "ddeadbeefdeadbeefdeadbeefdeadbeef")


# --- Bot API репост-бота ---


def test_build_application_without_proxy_does_not_crash():
    build_application()


def test_build_application_with_socks5_proxy_does_not_crash(monkeypatch):
    _set(monkeypatch, PROXY_SOCKS5_ENABLED="true",
         PROXY_SOCKS5_ADDRESS="1.2.3.4:1080", PROXY_SOCKS5_LOGIN="user",
         PROXY_SOCKS5_PASSWORD="pass", PROXY_USE_FOR_TELEGRAM="true")
    build_application()


# --- Guardian (свой отдельный прокси, не трогали) ---


def test_guardian_bot_api_proxy_url_defaults_empty():
    assert get_guardian_settings().bot_api_proxy_url == ""


def test_guardian_bot_api_proxy_url_read_from_env(monkeypatch):
    monkeypatch.setenv("GUARDIAN_BOT_API_PROXY_URL", "socks5://user:pass@1.2.3.4:1080")
    guardian_invalidate_settings_cache()
    assert get_guardian_settings().bot_api_proxy_url == "socks5://user:pass@1.2.3.4:1080"


def test_guardian_aiohttp_session_picks_up_proxy_without_crash(monkeypatch):
    monkeypatch.setenv("GUARDIAN_BOT_API_PROXY_URL", "socks5://user:pass@1.2.3.4:1080")
    guardian_invalidate_settings_cache()
    settings = get_guardian_settings()
    session = AiohttpSession(proxy=settings.bot_api_proxy_url)
    assert session._proxy == "socks5://user:pass@1.2.3.4:1080"


def test_guardian_settings_constructs_with_real_env_example_values(monkeypatch):
    values = dotenv_values(_ENV_EXAMPLE)
    for key, value in values.items():
        monkeypatch.setenv(key, value or "")
    GuardianSettings()  # type: ignore[call-arg]  # не должно бросить ValidationError


def test_guardian_aiohttp_session_with_malformed_proxy_url_raises_value_error():
    with pytest.raises(ValueError):
        AiohttpSession(proxy="not-a-valid-proxy-url")
