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
from tg_repost.enrichment.search import SearchResult, get_search_client
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


def split_by_language(selected: list[SearchResult]) -> tuple[list[SearchResult], list[SearchResult]]:
    """Разделить отобранные источники на (русскоязычные, англоязычные)."""
    ru = [s for s in selected if detect_language(f"{s.title} {s.description}") == "ru"]
    en = [s for s in selected if s not in ru]
    return ru, en


def format_sources_block(selected: list[SearchResult]) -> str:
    """Оформить блок «Источники:» со ссылками, разделёнными по языку."""
    if not selected:
        return ""
    ru, en = split_by_language(selected)

    lines = ["", "📚 Источники:"]
    if ru:
        lines.append("🇷🇺 Рус.:")
        lines.extend(f"• {s.title} — {s.url}" for s in ru)
    if en:
        lines.append("🌐 Англ.:")
        lines.extend(f"• {s.title} — {s.url}" for s in en)
    return "\n".join(lines)


_MAX_DISCREPANCY_LEN = 300


async def compare_source_versions(
    rewriter: RewriterClient,
    original_text: str,
    ru_sources: list[SearchResult],
    en_sources: list[SearchResult],
) -> str:
    """Спросить LLM, расходятся ли ru/en источники в трактовке события (F24).

    Возвращает короткую фразу о сути расхождения, либо пустую строку — если
    расхождений нет, источников одного из языков нет (сравнивать не с чем),
    или запрос не удался (не критично — как и остальное обогащение, F16).
    """
    if not ru_sources or not en_sources:
        return ""
    try:
        answer = await rewriter.complete(
            load_prompt("compare_sources").format(
                post_text=original_text,
                ru_sources=_format_results_for_prompt(ru_sources),
                en_sources=_format_results_for_prompt(en_sources),
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Сравнение версий источников не удалось: %s", exc)
        return ""
    answer = answer.strip()
    if not answer or answer.lower().startswith("нет"):
        return ""
    # Промпт просит короткую фразу, но LLM-ответ ничем не гарантирован по
    # длине (в т.ч. потенциальный prompt injection через содержимое
    # источников) — обрезаем, чтобы не вытеснить сам рерайченный текст поста
    # за пределы лимита Telegram при финальной отправке (найдено при код-
    # ревью Фазы 5+, тот же паттерн, что `_MAX_DETAIL_LEN`/`_MAX_LINE_LEN`
    # в audit.py/log_broadcast.py).
    if len(answer) > _MAX_DISCREPANCY_LEN:
        answer = answer[:_MAX_DISCREPANCY_LEN] + "…"
    return answer


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
    # Провайдер выбирается настройкой `search_provider` (searxng | brave |
    # ddgs) — см. enrichment/search.py::get_search_client.
    search = get_search_client()
    if not search.configured:
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
        results = await search.search(query, count=settings.enrichment_max_results)
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

        # F24 — сравнение версий: доп. LLM-вызов, только если есть источники
        # ОБОИХ языков (иначе сравнивать не с чем) и явно включено в настройках
        # (не критично для пайплайна — как и остальное обогащение).
        if block and settings.version_comparison_enabled:
            ru, en = split_by_language(selected)
            discrepancy = await compare_source_versions(rewriter, original_text, ru, en)
            if discrepancy:
                logger.info("F24: обнаружено расхождение версий источников: %s", discrepancy)
                block = f"\n⚠️ Разные версии события: {discrepancy}\n{block}"

        return block
    except Exception as exc:  # noqa: BLE001
        logger.warning("Обогащение источниками не удалось: %s", exc)
        return ""
