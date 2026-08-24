"""Список моделей провайдера для выбора в админке (2026-08-23).

ЗАЧЕМ. Модель вписывалась руками, и это стоило полдня разбора: в имени
`DeepSeek‑V3`, скопированном из чата, оказался неразрывный дефис U+2011 —
глазами не отличить, а провайдер такой модели не знает. Плюс у OmniRoute 368
моделей, и какие из них вообще отвечают этим ключом, узнать было неоткуда.

КАК УСТРОЕНО. Список забирается кнопкой (`/v1/models`) и кладётся в
настройки — одной строкой JSON, чтобы не заводить таблицу ради кэша.
Дальше поля моделей на странице настроек получают подсказку `<datalist>`:
можно выбрать из списка, а можно вписать своё.

ПОЧЕМУ ПОДСКАЗКА, А НЕ ЗАКРЫТЫЙ СПИСОК. Псевдонимы вроде `auto/cheap`
провайдер может не показывать в `/v1/models`, а работать они будут; локальный
llama.cpp вообще отдаёт одну строку с путём до файла. Закрытый список запретил
бы рабочие настройки — подсказка не запрещает ничего, но убирает главный
источник ошибок.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from openai import AsyncOpenAI

from tg_repost.config import get_settings
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

_SETTING_KEY = "provider_models_cache"
_FETCH_TIMEOUT_SECONDS = 45

# Как разложить список по назначению. Провайдер не говорит, что умеет
# модель, поэтому судим по имени — для ПОДСКАЗКИ этого достаточно, а
# ошибиться она не мешает: вписать можно что угодно.
_EMBEDDING_MARKERS = ("embed", "bge", "gte-", "e5-")
_IMAGE_MARKERS = ("flux", "dall", "stable-diffusion", "sd3", "imagen",
                  "kolors", "recraft", "ideogram", "-image", "image-")


@dataclass(frozen=True)
class ModelCatalog:
    """Что известно о моделях провайдера."""

    models: tuple[str, ...]
    fetched_at: datetime | None

    @property
    def chat(self) -> tuple[str, ...]:
        return tuple(
            m for m in self.models
            if not _looks_like(m, _EMBEDDING_MARKERS)
            and not _looks_like(m, _IMAGE_MARKERS)
        )

    @property
    def embedding(self) -> tuple[str, ...]:
        return tuple(m for m in self.models if _looks_like(m, _EMBEDDING_MARKERS))

    @property
    def image(self) -> tuple[str, ...]:
        return tuple(m for m in self.models if _looks_like(m, _IMAGE_MARKERS))


def _looks_like(model: str, markers: tuple[str, ...]) -> bool:
    low = model.lower()
    return any(marker in low for marker in markers)


def cached_catalog() -> ModelCatalog:
    """Что лежит в кэше. Пустой каталог — список ещё не забирали."""
    raw = get_settings().provider_models_cache.strip()
    if not raw:
        return ModelCatalog(models=(), fetched_at=None)
    try:
        data = json.loads(raw)
        models = tuple(str(m) for m in data.get("models", []))
        stamp = data.get("fetched_at")
        fetched = datetime.fromisoformat(stamp) if stamp else None
    except (json.JSONDecodeError, TypeError, ValueError):
        # Повреждённый кэш — не повод ронять страницу настроек: он всего
        # лишь подсказка, и её отсутствие ничего не ломает.
        logger.warning("Кэш списка моделей повреждён — показываю пустой")
        return ModelCatalog(models=(), fetched_at=None)
    return ModelCatalog(models=models, fetched_at=fetched)


async def refresh_catalog() -> ModelCatalog:
    """Забрать список у провайдера и сохранить. Бросает при отказе — вызов
    идёт по кнопке, и владелец должен увидеть причину, а не пустой список."""
    settings = get_settings()
    client = AsyncOpenAI(
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key or "sk-none",
        timeout=_FETCH_TIMEOUT_SECONDS,
        max_retries=0,
    )
    page = await client.models.list()
    models = tuple(sorted({str(item.id) for item in page.data}))
    fetched_at = datetime.now(timezone.utc)

    from tg_repost.webui.settings_store import save_setting

    save_setting(
        _SETTING_KEY,
        json.dumps({"fetched_at": fetched_at.isoformat(),
                    "models": list(models)}, ensure_ascii=False),
        "str",
    )
    logger.info("Список моделей обновлён: %d штук", len(models))
    return ModelCatalog(models=models, fetched_at=fetched_at)
