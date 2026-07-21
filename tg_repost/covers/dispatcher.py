"""Оркестрация авто-обложек (F18): выбор стратегии, сохранение файла.

Если у поста нет медиа и обложки включены — генерация через Unsplash
(стоковое фото по короткому запросу), ComfyUI (уникальная AI-картинка) или
"openai" (F18-доп.: любой OpenAI-совместимый провайдер картинок, уже
настроенный для рерайта, — свой промпт и модель, без search-запроса, см.
`covers/openai_compatible.py`). Выбор стратегии — `COVER_STRATEGY`. Любая
ошибка → None, рерайт никогда не должен падать из-за обложки.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from tg_repost.config import get_settings
from tg_repost.covers.comfyui import ComfyUIClient
from tg_repost.covers.openai_compatible import OpenAICompatibleImageClient
from tg_repost.covers.unsplash import UnsplashClient
from tg_repost.logging_conf import get_logger
from tg_repost.rewriter.client import RewriterClient, load_prompt

logger = get_logger(__name__)


async def _generate_by_search_query(prompt: str) -> bytes | None:
    """Unsplash/ComfyUI — оба принимают КОРОТКИЙ search-подобный запрос."""
    settings = get_settings()
    if settings.cover_strategy == "comfyui":
        return await ComfyUIClient().generate_image_bytes(prompt)
    return await UnsplashClient().fetch_random_photo_bytes(prompt)


async def generate_cover(rewriter: RewriterClient, post_text: str) -> str | None:
    """Сгенерировать обложку для поста и сохранить в media_dir.

    Возвращает путь к файлу или None (выключено/ошибка/не настроено).
    """
    settings = get_settings()
    if not settings.enable_auto_cover:
        return None

    try:
        if settings.cover_strategy == "openai":
            # Реальный генератор картинок, не поиск — можно отдать полный
            # описательный промпт напрямую, без промежуточного LLM-вызова
            # для короткого search-запроса (в отличие от unsplash/comfyui).
            prompt = settings.cover_image_prompt_template.format(post_text=post_text)
            image_bytes = await OpenAICompatibleImageClient().generate_image_bytes(prompt)
        else:
            # Промпт подбора search-запроса тоже редактируется в /settings
            # (раньше был доступен только правкой файла в репозитории, хотя
            # именно он определяет, что за картинка приедет). Пусто = откат
            # на файл, как было.
            template = (
                settings.cover_search_prompt_template.strip()
                or load_prompt("cover_prompt")
            )
            query = await rewriter.complete(template.format(post_text=post_text))
            query = query.strip().splitlines()[0] if query.strip() else ""
            if not query:
                return None
            image_bytes = await _generate_by_search_query(query)

        if not image_bytes:
            return None

        media_dir = Path(settings.media_dir)
        path = media_dir / f"cover_{uuid.uuid4().hex}.jpg"

        def _save() -> None:
            media_dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(image_bytes)

        await asyncio.to_thread(_save)
        logger.info("Обложка сгенерирована (%s): %s", settings.cover_strategy, path)
        return str(path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Генерация обложки не удалась: %s", exc)
        return None
