"""Клиент Brave Search API (F16).

Принимает поисковый запрос, возвращает топ-N результатов. Brave выбран из-за
бесплатного тира и цены ниже SerpAPI. Все сетевые ошибки логируются и приводят
к пустому списку — обогащение никогда не должно ломать основной пайплайн.
"""

from __future__ import annotations

from dataclasses import dataclass

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
