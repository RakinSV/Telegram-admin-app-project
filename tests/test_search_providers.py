"""Тесты диспетчера провайдеров поиска (F16) и клиента SearXNG.

Сети нет: HTTP подменяется, проверяется разбор ответа, отсев мусора и
поведение при ошибках — поиск НИКОГДА не должен ронять пайплайн рерайта,
максимум вернуть пустой список.
"""

from __future__ import annotations

import httpx
import pytest

from tg_repost.config import invalidate_settings_cache
from tg_repost.db.models import AppSetting
from tg_repost.db.session import session_scope
from tg_repost.enrichment.search import (
    SEARCH_PROVIDERS,
    BraveSearchClient,
    DDGSearchClient,
    SearXNGSearchClient,
    get_search_client,
)
from tg_repost.webui import settings_store

_KEYS = ("search_provider", "searxng_base_url", "searxng_engines", "searxng_language")


@pytest.fixture(autouse=True)
def _clean_settings():
    def _wipe() -> None:
        with session_scope() as session:
            session.query(AppSetting).filter(AppSetting.key.in_(_KEYS)).delete(
                synchronize_session=False,
            )
        invalidate_settings_cache()

    _wipe()
    yield
    _wipe()


# --- диспетчер ---


def test_default_provider_is_searxng():
    """Единственный вариант, бесплатный без оговорок: у Brave бесплатный тир
    закрыт для новых регистраций с февраля 2026."""
    assert isinstance(get_search_client(), SearXNGSearchClient)


@pytest.mark.parametrize(("name", "expected"), [
    ("searxng", SearXNGSearchClient),
    ("brave", BraveSearchClient),
    ("ddgs", DDGSearchClient),
])
def test_dispatcher_returns_selected_provider(name, expected):
    settings_store.save_setting("search_provider", name, "str")
    assert isinstance(get_search_client(), expected)


def test_unknown_provider_falls_back_to_searxng_without_crashing(caplog):
    """Опечатка в .env не должна ронять пайплайн — форма ограничена choices,
    но правку файла руками этим не остановить."""
    settings_store.save_setting("search_provider", "яндекс-которого-нет", "str")
    assert isinstance(get_search_client(), SearXNGSearchClient)
    assert "Неизвестный провайдер поиска" in caplog.text


def test_dispatcher_is_not_cached_between_calls():
    """Адрес SearXNG правится в админке живьём: закэшированный клиент ходил бы
    по старому адресу до перезапуска процесса."""
    settings_store.save_setting("searxng_base_url", "http://first:8080", "str")
    first = get_search_client()
    settings_store.save_setting("searxng_base_url", "http://second:8080", "str")
    second = get_search_client()
    assert first._base_url != second._base_url


def test_every_provider_name_has_a_client():
    for name in SEARCH_PROVIDERS:
        settings_store.save_setting("search_provider", name, "str")
        assert get_search_client() is not None


def test_provider_choices_in_admin_match_the_code():
    """Список в выпадашке и карта провайдеров не должны разъезжаться —
    иначе в UI появится вариант, который молча откатывается на searxng."""
    field = next(
        f
        for g in settings_store.SETTINGS_GROUPS
        for f in g.fields
        if f.name == "search_provider"
    )
    assert field.choices is not None
    assert set(field.choices) == set(SEARCH_PROVIDERS)


# --- SearXNG ---


def _searxng_with(monkeypatch, payload: dict, *, capture: list | None = None):
    client = SearXNGSearchClient()

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return payload

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None, **kwargs):
            if capture is not None:
                capture.append((url, params))
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _Client())
    return client


def test_searxng_configured_requires_base_url():
    settings_store.save_setting("searxng_base_url", "", "str")
    assert SearXNGSearchClient().configured is False
    settings_store.save_setting("searxng_base_url", "http://searxng:8080", "str")
    assert SearXNGSearchClient().configured is True


@pytest.mark.asyncio
async def test_searxng_parses_results(monkeypatch):
    payload = {"results": [
        {"title": "Заголовок", "url": "https://example.com/a", "content": "Описание"},
        {"title": "Second", "url": "https://example.com/b"},
    ]}
    client = _searxng_with(monkeypatch, payload)
    results = await client.search("запрос")

    assert [r.url for r in results] == ["https://example.com/a", "https://example.com/b"]
    # У SearXNG поле называется content, а не description.
    assert results[0].description == "Описание"
    assert results[1].description == ""


@pytest.mark.asyncio
async def test_searxng_skips_entries_without_url_or_title(monkeypatch):
    payload = {"results": [
        {"title": "нет url"},
        {"url": "https://example.com/no-title"},
        {"title": "ok", "url": "https://example.com/ok"},
    ]}
    client = _searxng_with(monkeypatch, payload)
    results = await client.search("q")
    assert [r.url for r in results] == ["https://example.com/ok"]


@pytest.mark.asyncio
async def test_searxng_respects_count(monkeypatch):
    payload = {"results": [
        {"title": f"t{i}", "url": f"https://example.com/{i}"} for i in range(20)
    ]}
    client = _searxng_with(monkeypatch, payload)
    assert len(await client.search("q", count=5)) == 5


@pytest.mark.asyncio
async def test_searxng_asks_for_json_format(monkeypatch):
    """Без format=json SearXNG отдаёт HTML — разбор бы молча ничего не нашёл."""
    captured: list = []
    client = _searxng_with(monkeypatch, {"results": []}, capture=captured)
    await client.search("q")
    _url, params = captured[0]
    assert params["format"] == "json"
    assert params["q"] == "q"


@pytest.mark.asyncio
async def test_searxng_omits_empty_engines_and_language(monkeypatch):
    """Пустой engines= для SearXNG означает НЕ «все движки», а «ни одного» —
    выдача молча приходит пустой."""
    settings_store.save_setting("searxng_engines", "", "str")
    settings_store.save_setting("searxng_language", "", "str")
    captured: list = []
    client = _searxng_with(monkeypatch, {"results": []}, capture=captured)
    await client.search("q")
    _url, params = captured[0]
    assert "engines" not in params
    assert "language" not in params


@pytest.mark.asyncio
async def test_searxng_passes_engines_and_language_when_set(monkeypatch):
    settings_store.save_setting("searxng_engines", "google,yandex", "str")
    settings_store.save_setting("searxng_language", "ru", "str")
    captured: list = []
    client = _searxng_with(monkeypatch, {"results": []}, capture=captured)
    await client.search("q")
    _url, params = captured[0]
    assert params["engines"] == "google,yandex"
    assert params["language"] == "ru"


@pytest.mark.asyncio
async def test_searxng_network_error_returns_empty_not_raises(monkeypatch):
    class _Boom:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *a, **kw):
            raise httpx.ConnectError("searxng недоступен")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _Boom())
    assert await SearXNGSearchClient().search("q") == []


@pytest.mark.asyncio
async def test_searxng_blank_query_makes_no_request(monkeypatch):
    captured: list = []
    client = _searxng_with(monkeypatch, {"results": []}, capture=captured)
    assert await client.search("   ") == []
    assert captured == []


@pytest.mark.asyncio
async def test_searxng_without_base_url_returns_empty():
    settings_store.save_setting("searxng_base_url", "", "str")
    assert await SearXNGSearchClient().search("q") == []
