"""Оркестрация обогащения поста источниками (F16).

Шаги:
  1. LLM выделяет поисковый запрос из оригинала (keywords.txt).
  2. Brave Search возвращает топ-N результатов.
  3. LLM отбирает до K релевантных (select_sources.txt), возвращая их номера.
  4. Отобранные источники делятся на русско- и англоязычные и оформляются
     блоком «Источники:» для добавления в конец рерайченного поста.

Любая ошибка/пустой результат → пустая строка: обогащение не должно ломать
основной пайплайн рерайта.
"""

from __future__ import annotations

import re

from tg_repost.config import get_settings
from tg_repost.db.models import Source
from tg_repost.enrichment.search import BraveSearchClient, SearchResult
from tg_repost.logging_conf import get_logger
from tg_repost.rewriter.client import RewriterClient, load_prompt

logger = get_logger(__name__)

_CYRILLIC_RE = re.compile(r"[а-яёА-ЯЁ]")
_INDEX_RE = re.compile(r"\d+")


def detect_language(text: str) -> str:
    """Грубое определение языка по наличию кириллицы: 'ru' или 'en'."""
    return "ru" if _CYRILLIC_RE.search(text or "") else "en"


def parse_indices(answer: str, total: int) -> list[int]:
    """Разобрать ответ LLM с номерами (1-based) в валидные 0-based индексы."""
    if not answer or "нет" in answer.strip().lower():
        return []
    seen: set[int] = set()
    result: list[int] = []
    for match in _INDEX_RE.findall(answer):
        idx = int(match) - 1
        if 0 <= idx < total and idx not in seen:
            seen.add(idx)
            result.append(idx)
    return result


def format_sources_block(selected: list[SearchResult]) -> str:
    """Оформить блок «Источники:» со ссылками, разделёнными по языку."""
    if not selected:
        return ""
    ru = [s for s in selected if detect_language(f"{s.title} {s.description}") == "ru"]
    en = [s for s in selected if s not in ru]

    lines = ["", "📚 Источники:"]
    if ru:
        lines.append("🇷🇺 Рус.:")
        lines.extend(f"• {s.title} — {s.url}" for s in ru)
    if en:
        lines.append("🌐 Англ.:")
        lines.extend(f"• {s.title} — {s.url}" for s in en)
    return "\n".join(lines)


def _format_results_for_prompt(results: list[SearchResult]) -> str:
    """Пронумерованный список результатов для промпта отбора."""
    return "\n".join(
        f"{i + 1}. {r.title} — {r.url}\n   {r.description}"
        for i, r in enumerate(results)
    )


def enrichment_enabled_for(source: Source | None) -> bool:
    """Включено ли обогащение: per-source override имеет приоритет над глобальным."""
    settings = get_settings()
    if source is not None and source.enrich_sources is not None:
        return bool(source.enrich_sources)
    return settings.enable_source_enrichment


async def enrich_post(rewriter: RewriterClient, original_text: str) -> str:
    """Вернуть блок «Источники:» для поста или пустую строку при неудаче."""
    settings = get_settings()
    brave = BraveSearchClient()
    if not brave.configured:
        return ""

    try:
        # 1. Поисковый запрос из оригинала.
        query = await rewriter.complete(
            load_prompt("keywords").format(post_text=original_text)
        )
        query = query.strip().splitlines()[0] if query.strip() else ""
        if not query:
            return ""

        # 2. Поиск.
        results = await brave.search(query, count=settings.enrichment_max_results)
        if not results:
            return ""

        # 3. Отбор релевантных через LLM (возвращает номера).
        answer = await rewriter.complete(
            load_prompt("select_sources").format(
                post_text=original_text,
                results=_format_results_for_prompt(results),
                max_sources=settings.enrichment_max_sources,
            )
        )
        indices = parse_indices(answer, len(results))[: settings.enrichment_max_sources]
        selected = [results[i] for i in indices]

        # 4. Оформление блока.
        block = format_sources_block(selected)
        if block:
            logger.info("Обогащение: добавлено источников %d (запрос '%s')",
                        len(selected), query)
        return block
    except Exception as exc:  # noqa: BLE001
        logger.warning("Обогащение источниками не удалось: %s", exc)
        return ""
