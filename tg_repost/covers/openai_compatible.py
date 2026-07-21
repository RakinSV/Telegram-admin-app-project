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

# Защита от переполнения памяти/диска, если провайдер (или MITM при случайно
# незашифрованном openai_base_url) вернёт аномально большой b64_json —
# найдено на security-ревью: раньше декодирование и запись были не ограничены
# по размеру (в отличие от enrichment/link_content.py::_MAX_DOWNLOAD_BYTES).
_MAX_IMAGE_BYTES = 10_000_000


def _decode_image(b64_json: str | None) -> bytes | None:
    """Декодировать base64-картинку из ответа images.generate(). None при
    отсутствии данных, битой base64-строке или превышении лимита размера."""
    if not b64_json:
        return None
    # Грубая проверка ДО декодирования (base64 раздувает исходный размер
    # на ~33% — с запасом), точная проверка декодированной длины — ниже.
    if len(b64_json) > _MAX_IMAGE_BYTES * 2:
        return None
    try:
        data = base64.b64decode(b64_json)
    except (binascii.Error, ValueError):
        return None
    if len(data) > _MAX_IMAGE_BYTES:
        return None
    return data


class OpenAICompatibleImageClient:
    """Асинхронный клиент генерации картинок через images.generate()."""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncOpenAI(
            base_url=settings.openai_base_url, api_key=settings.openai_api_key,
        )
        self._model = settings.cover_openai_model
        self._size = settings.cover_openai_image_size

    async def generate_image_bytes(self, prompt: str) -> bytes | None:
        """Сгенерировать картинку по промпту. None при любой ошибке — как и
        остальные стратегии обложек, не должна ронять основной рерайт."""
        if not prompt.strip():
            return None
        try:
            response = await self._client.images.generate(
                model=self._model, prompt=prompt, size=self._size, n=1,  # type: ignore[arg-type]
                response_format="b64_json",
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
