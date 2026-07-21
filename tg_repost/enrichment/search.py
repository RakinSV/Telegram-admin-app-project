"""Веб-поиск для добора источников (F16): провайдер выбирается настройкой.

Принимает поисковый запрос, возвращает топ-N результатов. Все сетевые ошибки
логируются и приводят к ПУСТОМУ списку — обогащение никогда не должно ломать
основной пайплайн рерайта.

Провайдеры (`search_provider`):

* `searxng` — свой метапоисковик в Docker (см. docker-compose.yml). Бесплатен
  без оговорок: ни ключа, ни аккаунта, ни квоты, плюс сам выбираешь, какие
  движки опрашивать — важно там, где часть выдачи недоступна из сети сервера.
* `brave` — Brave Search API. ВНИМАНИЕ: бесплатный тир закрыт для новых
  регистраций в феврале 2026 (осталось $5 кредитов в месяц, ~1000 запросов,
  и то при условии публичной атрибуции). Раньше провайдер выбирался именно
  из-за бесплатного тира — это больше не так, ключ остаётся рабочим только
  у тех, кто успел подписаться раньше.
* `ddgs` — DuckDuckGo через одноимённую библиотеку: ключ не нужен, но она
  неофициальная и ловит троттлинг (202/403), поэтому зависимость
  опциональная (импорт внутри метода) и как основной режим не рекомендуется.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

import httpx

from tg_repost.config import get_settings
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class SearchResult:
    """Один результат веб-поиска."""

    title: str
    url: str
    description: str = ""


class SearchClient(Protocol):
    """Общий контракт провайдеров поиска — на него смотрит `enricher.py`."""

    @property
    def configured(self) -> bool:
        """Готов ли провайдер работать (есть ключ / задан адрес)."""
        ...

    async def search(self, query: str, count: int = 8) -> list[SearchResult]:
        """Топ-N результатов. Пустой список при любой ошибке."""
        ...


class BraveSearchClient:
    """Асинхронный клиент Brave Search."""

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.brave_api_key
        self._url = settings.brave_search_url

    @property
    def configured(self) -> bool:
        """Задан ли API-ключ."""
        return bool(self._api_key)

    async def search(self, query: str, count: int = 8) -> list[SearchResult]:
        """Выполнить поиск. Возвращает список результатов (пустой при ошибке)."""
        if not self.configured:
            logger.warning("BRAVE_API_KEY не задан — поиск источников пропущен")
            return []
        if not query.strip():
            return []

        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self._api_key,
        }
        params: dict[str, str | int] = {"q": query, "count": count}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(self._url, headers=headers, params=params)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Brave Search ошибка: %s", exc)
            return []

        return self._parse(data)

    @staticmethod
    def _parse(data: dict) -> list[SearchResult]:
        results: list[SearchResult] = []
        web = data.get("web") or {}
        for item in web.get("results", []) or []:
            url = item.get("url")
            title = item.get("title")
            if not url or not title:
                continue
            results.append(
                SearchResult(
                    title=title.strip(),
                    url=url.strip(),
                    description=(item.get("description") or "").strip(),
                )
            )
        return results


class SearXNGSearchClient:
    """Клиент своего SearXNG (метапоисковик в Docker, JSON API).

    Ключа и аккаунта не требует — сервис свой. Единственное условие: в его
    `settings.yml` должен быть включён формат `json` (по умолчанию активен
    только `html`), иначе на запрос приедет 403.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.searxng_base_url.rstrip("/")
        self._engines = settings.searxng_engines.strip()
        self._language = settings.searxng_language.strip()

    @property
    def configured(self) -> bool:
        return bool(self._base_url)

    async def search(self, query: str, count: int = 8) -> list[SearchResult]:
        if not self.configured:
            logger.warning("SEARXNG_BASE_URL не задан — поиск источников пропущен")
            return []
        if not query.strip():
            return []

        params: dict[str, str] = {"q": query, "format": "json"}
        # Пустые значения НЕ отправляем: для SearXNG пустой `engines=` — это
        # не «все движки», а «ни одного», и выдача молча приходит пустой.
        if self._engines:
            params["engines"] = self._engines
        if self._language:
            params["language"] = self._language

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.get(f"{self._base_url}/search", params=params)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("SearXNG ошибка: %s", exc)
            return []

        return self._parse(data, count)

    @staticmethod
    def _parse(data: dict, count: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        for item in data.get("results", []) or []:
            url = item.get("url")
            title = item.get("title")
            if not url or not title:
                continue
            results.append(
                SearchResult(
                    title=str(title).strip(),
                    url=str(url).strip(),
                    # У SearXNG поле называется `content`, а не `description`.
                    description=(item.get("content") or "").strip(),
                )
            )
            if len(results) >= count:
                break
        return results


class DDGSearchClient:
    """DuckDuckGo через библиотеку `ddgs` — без ключа, но неофициально.

    Библиотека синхронная, поэтому вызов уносится в поток: прямой вызов
    заблокировал бы ОБЩИЙ event loop (Telethon-listener, бот, планировщик —
    один процесс), тот же приём, что для DNS-резолва в `link_content.py`.

    Зависимость опциональная и импортируется внутри метода: она неофициальная
    и ловит троттлинг, поэтому не должна лежать в requirements.txt как
    обязательная и ронять сборку тем, кто ей не пользуется.
    """

    @property
    def configured(self) -> bool:
        # Подавление проверки типов на импортах ниже: зависимость намеренно
        # НЕ в requirements.txt (неофициальная, ловит троттлинг), поэтому
        # типов для неё в окружении сборки нет, и это не ошибка.
        try:
            import ddgs  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            return False
        return True

    async def search(self, query: str, count: int = 8) -> list[SearchResult]:
        if not query.strip():
            return []
        try:
            from ddgs import DDGS  # type: ignore[import-not-found]
        except ImportError:
            logger.warning(
                "Провайдер поиска 'ddgs' выбран, но библиотека не установлена "
                "(pip install ddgs) — поиск источников пропущен",
            )
            return []

        def _run() -> list[dict]:
            with DDGS() as client:
                return list(client.text(query, max_results=count))

        try:
            raw = await asyncio.to_thread(_run)
        except Exception as exc:  # noqa: BLE001
            # Троттлинг DuckDuckGo (202/403) — штатный сценарий, не авария.
            logger.warning("DuckDuckGo ошибка: %s", exc)
            return []

        results: list[SearchResult] = []
        for item in raw:
            url = item.get("href") or item.get("url")
            title = item.get("title")
            if not url or not title:
                continue
            results.append(
                SearchResult(
                    title=str(title).strip(),
                    url=str(url).strip(),
                    description=(item.get("body") or "").strip(),
                )
            )
        return results


# Имя провайдера из настроек → класс клиента. Порядок ключей = порядок в
# выпадающем списке на /settings.
_PROVIDERS: dict[str, type] = {
    "searxng": SearXNGSearchClient,
    "brave": BraveSearchClient,
    "ddgs": DDGSearchClient,
}

SEARCH_PROVIDERS: tuple[str, ...] = tuple(_PROVIDERS)


def get_search_client() -> SearchClient:
    """Клиент поиска по текущей настройке `search_provider`.

    Клиент создаётся на КАЖДЫЙ вызов, а не кэшируется: адрес SearXNG и ключ
    Brave правятся в админке живьём, и закэшированный экземпляр продолжал бы
    ходить по старому адресу до перезапуска процесса (ровно та ошибка, что
    уже ловилась на `RewriterClient`, см. комментарий у `get_rewriter()`).

    Неизвестное значение настройки не должно ронять пайплайн: откатываемся на
    SearXNG и говорим об этом в лог. Сама настройка ограничена списком
    `choices` на уровне формы, так что сюда это попадает только при правке
    `.env` руками.
    """
    name = get_settings().search_provider
    client_cls = _PROVIDERS.get(name)
    if client_cls is None:
        logger.warning(
            "Неизвестный провайдер поиска '%s' — использую searxng. Допустимые: %s",
            name, ", ".join(SEARCH_PROVIDERS),
        )
        client_cls = SearXNGSearchClient
    return client_cls()  # type: ignore[no-any-return]
