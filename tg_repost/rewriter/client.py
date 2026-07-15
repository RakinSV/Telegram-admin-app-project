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

# Известные стиль-профили рерайта (F15). default — нейтральный.
KNOWN_STYLES = ("default", "news", "opinion", "instruction", "humor")


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

    Стиль "default" читается из редактируемой в `/settings` настройки
    `rewrite_prompt_template` (пользователь правит текст без git/передеплоя);
    `default.txt` — запасной вариант только если поле очистили пустым.
    Остальные стили (news/opinion/instruction/humor, F15) — по-прежнему
    из файлов `prompts/*.txt`, как раньше.
    """
    if prompt_name == "default":
        return get_settings().rewrite_prompt_template.strip() or load_prompt("default")
    return load_prompt(prompt_name)


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
        template = resolve_rewrite_template(prompt_name)
        prompt = template.format(post_text=post_text, link_content=link_content)

        logger.debug(
            "Запрос рерайта: model=%s, стиль=%s, длина=%d",
            self._model, prompt_name, len(post_text),
        )

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
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
