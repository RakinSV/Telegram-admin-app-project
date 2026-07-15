"""Генерация обложек через OpenAI-совместимый images-эндпоинт (F18-доп.).

Использует УЖЕ настроенный клиент рерайта (`openai_base_url`/`openai_api_key`,
см. `rewriter/client.py`) — отдельный ключ не нужен, только своя (картиночная)
модель, см. `cover_openai_model`. Работает с любым провайдером, отдающим
`data[].b64_json` из `images.generate()` — стандартный формат DALL-E-подобных
API, так уже отдают Flux/Gemini-image/GPT-Image через routerai.ru (проверено
живым вызовом).
"""

from __future__ import annotations

import base64
import binascii

from openai import AsyncOpenAI

from tg_repost.config import get_settings
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)


def _decode_image(b64_json: str | None) -> bytes | None:
    """Декодировать base64-картинку из ответа images.generate(). None при
    отсутствии данных или битой base64-строке."""
    if not b64_json:
        return None
    try:
        return base64.b64decode(b64_json)
    except (binascii.Error, ValueError):
        return None


class OpenAICompatibleImageClient:
    """Асинхронный клиент генерации картинок через images.generate()."""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncOpenAI(
            base_url=settings.openai_base_url, api_key=settings.openai_api_key,
        )
        self._model = settings.cover_openai_model

    async def generate_image_bytes(self, prompt: str) -> bytes | None:
        """Сгенерировать картинку по промпту. None при любой ошибке — как и
        остальные стратегии обложек, не должна ронять основной рерайт."""
        if not prompt.strip():
            return None
        try:
            response = await self._client.images.generate(
                model=self._model, prompt=prompt, size="1024x1024", n=1,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Генерация обложки не удалась (модель %s): %s", self._model, exc,
            )
            return None

        item = response.data[0] if response.data else None
        image_bytes = _decode_image(getattr(item, "b64_json", None) if item else None)
        if image_bytes is None:
            logger.warning(
                "Провайдер не вернул валидный b64_json для обложки (модель %s)", self._model,
            )
        return image_bytes
