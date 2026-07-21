"""Клиент рерайта (F06) поверх OpenAI-совместимого API.

Провайдер меняется через `.env` (`OPENAI_BASE_URL`/`OPENAI_API_KEY`/
`OPENAI_MODEL`), не в коде. Промпт-шаблоны хранятся в файлах
(`rewriter/prompts/*.txt`), а не хардкодятся, чтобы их можно было итерировать
без передеплоя. Стиль-профили (F15) — это разные файлы промптов.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from openai import AsyncOpenAI

from tg_repost.config import get_settings
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"

# Имя настройки с текстом промпта для каждого стиль-профиля (F15). Раньше поле
# было только у "default", а остальные стили читались прямо из файлов —
# источник со `style_profile="news"` молча игнорировал промпт, отредактированный
# в админке. Теперь редактируются все; файл `prompts/<стиль>.txt` остаётся
# запасным вариантом, если поле очистили пустым.
#
# Порядок ключей = порядок в выпадающем списке стилей на /sources/{id}.
_STYLE_SETTING_FIELDS = {
    "default": "rewrite_prompt_template",
    "news": "rewrite_prompt_news",
    "opinion": "rewrite_prompt_opinion",
    "instruction": "rewrite_prompt_instruction",
    "humor": "rewrite_prompt_humor",
}

# Известные стиль-профили рерайта (F15). default — нейтральный. Выводится из
# карты выше, а не отдельным литералом: иначе стиль, добавленный только в один
# из двух списков, снова появился бы в UI с нередактируемым промптом.
KNOWN_STYLES = tuple(_STYLE_SETTING_FIELDS)


@dataclass
class RewriteResult:
    """Результат рерайта: текст и метрики токенов."""

    text: str
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@lru_cache
def load_prompt(name: str = "default") -> str:
    """Загрузить промпт-шаблон по имени (без расширения)."""
    path = _PROMPTS_DIR / f"{name}.txt"
    return path.read_text(encoding="utf-8")


def prompt_exists(name: str) -> bool:
    """Есть ли файл промпта с таким именем."""
    return bool(name) and (_PROMPTS_DIR / f"{name}.txt").exists()


def resolve_style_prompt(style: str | None) -> str:
    """Выбрать имя промпта по стилю источника (F15).

    Берём стиль источника; если он пуст или для него нет файла — профиль по
    умолчанию из настроек; если и его нет — `default`.
    """
    settings = get_settings()
    for candidate in (style, settings.default_style_profile):
        if candidate and prompt_exists(candidate):
            return candidate
    return "default"


def resolve_rewrite_template(prompt_name: str) -> str:
    """Выбрать шаблон промпта для `RewriterClient.rewrite()`.

    Приоритет: настройка из `/settings` → одноимённый файл `prompts/*.txt`.
    Стиль, которого нет ни в настройках, ни среди файлов, — не ошибка на
    этом уровне: `resolve_style_prompt()` выше уже отфильтровал такие имена.
    """
    field = _STYLE_SETTING_FIELDS.get(prompt_name)
    if field:
        configured = str(getattr(get_settings(), field, "")).strip()
        if configured:
            return configured
    return load_prompt(prompt_name)


def build_rewrite_prompt(
    prompt_name: str, post_text: str, link_content: str = "",
) -> str:
    """Собрать финальный промпт: шаблон стиля + анти-ИИ блок.

    Анти-ИИ блок (`rewrite_humanize_instructions`) добавляется ОДИН на все
    стили и ПОСЛЕ шаблона — инструкции в конце промпта модель соблюдает
    заметно охотнее, чем закопанные в середину, а держать пять копий одного
    и того же правила в пяти шаблонах означало бы гарантированно разъехавшиеся
    редакции.
    """
    template = resolve_rewrite_template(prompt_name)
    prompt = template.format(post_text=post_text, link_content=link_content)

    settings = get_settings()
    if settings.rewrite_humanize_enabled:
        humanize = settings.rewrite_humanize_instructions.strip()
        if humanize:
            prompt = f"{prompt}\n\n{humanize}"
    return prompt


class RewriterClient:
    """Асинхронный клиент рерайта/эмбеддингов."""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncOpenAI(
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
        )
        self._model = settings.openai_model
        self._embedding_model = settings.openai_embedding_model

    async def rewrite(
        self, post_text: str, prompt_name: str = "default", link_content: str = "",
    ) -> RewriteResult:
        """Переписать текст поста выбранным стиль-профилем (F06/F15).

        `link_content` — текст статьи по ссылке из поста (F16-доп., см.
        `enrichment/link_content.py`), пусто — если ссылки не было или
        переход не удался, тогда рерайт идёт только по `post_text`, как
        раньше.
        """
        prompt = build_rewrite_prompt(prompt_name, post_text, link_content)
        # Настройки читаются на КАЖДЫЙ вызов, а не кэшируются в __init__:
        # температура и промпты правятся в /settings живьём, без пересборки
        # клиента (в отличие от base_url/api_key/модели — те в конструкторе
        # AsyncOpenAI, поэтому требуют resync, см. get_rewriter()).
        temperature = get_settings().rewrite_temperature

        logger.debug(
            "Запрос рерайта: model=%s, стиль=%s, длина=%d, ссылка=%s, t=%.2f",
            self._model, prompt_name, len(post_text), bool(link_content), temperature,
        )

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )

        text = (response.choices[0].message.content or "").strip()
        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0

        logger.info(
            "Рерайт готов (стиль=%s): токены prompt=%d completion=%d",
            prompt_name, prompt_tokens, completion_tokens,
        )
        return RewriteResult(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    async def complete(self, prompt: str, *, temperature: float = 0.3) -> str:
        """Одноразовый LLM-вызов для вспомогательных задач (F16: ключевые слова,
        отбор релевантных источников). Возвращает текст ответа."""
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        return (response.choices[0].message.content or "").strip()

    async def embed(self, text: str) -> list[float]:
        """Получить эмбеддинг текста (F13). Бросает исключение при ошибке API."""
        response = await self._client.embeddings.create(
            model=self._embedding_model,
            input=text,
        )
        return list(response.data[0].embedding)


@lru_cache
def get_rewriter() -> RewriterClient:
    """Кэшированный синглтон клиента рерайта/эмбеддингов — используется
    ТОЛЬКО `telegram/listener.py` для эмбеддингов дедупа (F13) при захвате
    сообщения. Не путать с `webui.supervisor._components.rewriter` —
    отдельный, независимо пересобираемый экземпляр для pipeline_tick/
    digest_job. Два разных кэша одного и того же класса: `_sync_jobs()`
    пересобирает `_components.rewriter`, но НЕ трогает этот — без явного
    `invalidate_rewriter_cache()` эмбеддинги в listener.py продолжали бы
    работать со старым base_url/моделью бесконечно, даже после resync
    (найдено на реальном деплое: смена модели рерайта применилась к
    pipeline_tick, а "Не удалось получить эмбеддинг" в listener.py — нет)."""
    return RewriterClient()


def invalidate_rewriter_cache() -> None:
    """Сбросить кэш `get_rewriter()` — вызывать вместе с пересборкой
    `_components.rewriter` (см. `webui/supervisor.py::_sync_jobs`)."""
    get_rewriter.cache_clear()
