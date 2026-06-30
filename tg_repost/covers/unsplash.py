"""Клиент Unsplash API (F18) — обложка по ключевым словам, без AI-генерации.

Быстрее и бесплатнее ComfyUI, но не уникальна (готовое стоковое фото).
"""

from __future__ import annotations

import httpx

from tg_repost.config import get_settings
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)


class UnsplashClient:
    """Асинхронный клиент случайного фото Unsplash по запросу."""

    def __init__(self) -> None:
        settings = get_settings()
        self._access_key = settings.unsplash_access_key
        self._url = settings.unsplash_api_url

    @property
    def configured(self) -> bool:
        """Задан ли API-ключ."""
        return bool(self._access_key)

    @staticmethod
    def extract_image_url(data: dict) -> str | None:
        """Достать URL изображения "regular" размера из ответа Unsplash."""
        urls = data.get("urls") or {}
        return urls.get("regular") or urls.get("full") or urls.get("small")

    async def fetch_random_photo_bytes(self, query: str) -> bytes | None:
        """Скачать случайное фото по запросу. None при ошибке/не настроено."""
        if not self.configured or not query.strip():
            return None

        headers = {"Authorization": f"Client-ID {self._access_key}"}
        params = {"query": query, "orientation": "landscape"}

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.get(self._url, headers=headers, params=params)
                response.raise_for_status()
                data = response.json()
                image_url = self.extract_image_url(data)
                if not image_url:
                    logger.warning("Unsplash: в ответе нет URL изображения")
                    return None
                image_response = await client.get(image_url)
                image_response.raise_for_status()
                return image_response.content
        except Exception as exc:  # noqa: BLE001
            logger.warning("Unsplash ошибка: %s", exc)
            return None
