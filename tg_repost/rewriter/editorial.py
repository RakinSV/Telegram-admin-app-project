"""Редакция из двух агентов (F40): профессиональный рерайт через цикл
черновик → рецензия → правка.

Раньше рерайт был «в один присест»: модель писала пост начисто, и никто его
не правил. Здесь тот же клиент используется как ДВА агента:

  1. Журналист (client.rewrite) — пишет черновик по источникам.
  2. Редактор-фактчекер (client.rewrite_with_prompt на editor-промпте) —
     сверяет черновик с источниками, пишет замечания и вердикт, помечает
     спорные факты на веб-сверку.
  3. Журналист снова (client.rewrite_with_prompt на revise-промпте) —
     переписывает по замечаниям и находкам из интернета.

Цикл повторяется до вердикта OK или до `editorial_max_rounds`. Дороже по
токенам (1 раунд = 3 вызова LLM на вариант), поэтому включается настройкой.

Стоимость и устойчивость: ошибку оплаты (402) на ЛЮБОМ шаге пробрасываем
наверх — пусть пайплайн остановит пачку (см. scheduler/jobs.py). Прочие сбои
на рецензии/правке НЕ фатальны: лучше вернуть хороший черновик, чем потерять
пост из-за флапнувшего второго вызова.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from tg_repost import languages
from tg_repost.config import get_settings
from tg_repost.enrichment.search import get_search_client
from tg_repost.logging_conf import get_logger
from tg_repost.rewriter.client import (
    RewriterClient,
    is_billing_error,
    resolve_rewrite_template,
)

logger = get_logger(__name__)

# Фактчек должен быть детерминированным, а не «творческим»: рецензию гоним на
# низкой температуре независимо от rewrite_temperature (та — для письма).
_EDITOR_TEMPERATURE = 0.2

_VERDICT_REVISE_RE = re.compile(r"ВЕРДИКТ\s*:?\s*ПРАВИТЬ", re.IGNORECASE)
_VERDICT_OK_RE = re.compile(r"ВЕРДИКТ\s*:?\s*OK", re.IGNORECASE)
_CHECK_HEADER_RE = re.compile(r"^\s*ПРОВЕРИТЬ\s*:?\s*$", re.IGNORECASE)

_APPROVED_NOTE = "✓ Редактор одобрил без правок."

# Трансляция хода редакции наружу (F50, «редакционная кухня»): callback
# получает (стадия, текст). Стадии — константы ниже. Модуль намеренно НЕ знает,
# куда это уходит: в Telegram-чат, в лог или в список в тесте — решает
# вызывающий (`scheduler/jobs.py`). Так editorial.py остаётся свободен от
# зависимостей на Telegram и БД.
StepCallback = Callable[[str, str], Awaitable[None]]

STEP_DRAFT = "draft"
STEP_REVIEW = "review"
STEP_WEB_FINDINGS = "web_findings"
STEP_REVISION = "revision"
STEP_VERDICT = "verdict"


async def _emit(on_step: StepCallback | None, stage: str, text: str) -> None:
    """Отдать шаг наружу. Сбой трансляции НИКОГДА не влияет на рерайт — это
    диагностика, а не часть пайплайна (упавший Telegram не должен стоить поста)."""
    if on_step is None:
        return
    try:
        await on_step(stage, text)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Трансляция шага '%s' не удалась: %s", stage, exc)


@dataclass
class EditorialResult:
    """Итог редакционного цикла для одного варианта."""

    text: str
    tokens: int
    rounds_used: int  # сколько раз реально переписывали по замечаниям
    notes: str  # замечания редактора для показа на модерации ("" если не было)


def _build_sources(original: str, link_content: str) -> str:
    parts = [f"Исходный пост:\n{original.strip()}"]
    if link_content and link_content.strip():
        parts.append(f"Статья по ссылке:\n{link_content.strip()}")
    return "\n\n".join(parts)


def _language_line(language: str | None) -> str:
    if not language:
        return ""
    return f"\nТребуемый язык поста: {languages.label(language)}.\n"


def _parse_editor_output(text: str) -> tuple[bool, str, list[str]]:
    """Разобрать ответ редактора → (одобрено, текст_замечаний, факты_на_сверку).

    Одобрено = есть «ВЕРДИКТ: OK» и НЕТ «ВЕРДИКТ: ПРАВИТЬ» (при конфликте
    выбираем осторожное «править»). Если вердикта нет вовсе, но текст
    непустой — считаем за замечания (лучше лишний раз переписать)."""
    stripped = text.strip()
    revise = bool(_VERDICT_REVISE_RE.search(stripped))
    ok = bool(_VERDICT_OK_RE.search(stripped))
    approved = ok and not revise
    return approved, stripped, _extract_claims(stripped)


def _extract_claims(text: str) -> list[str]:
    """Вытащить утверждения из блока `ПРОВЕРИТЬ:` (до первой пустой строки)."""
    claims: list[str] = []
    capturing = False
    for line in text.splitlines():
        if _CHECK_HEADER_RE.match(line):
            capturing = True
            continue
        if capturing:
            # Набор СИМВОЛОВ, а не строка: снимаем пробелы, дефисы, буллеты
            # и табы в любом порядке. ruff предупреждает про многосимвольный
            # strip как про частую путаницу — здесь это ровно то, что нужно.
            item = line.strip(" -•\t•")  # noqa: B005
            if not item:
                break
            claims.append(item)
    return claims


async def _web_findings(claims: list[str], max_claims: int) -> str:
    """Догнать спорные факты веб-поиском (F16-клиент). Пусто — если поиск не
    настроен, ничего не нашлось или всё упало (не критично для правки)."""
    client = get_search_client()
    if not client.configured or max_claims <= 0:
        return ""
    blocks: list[str] = []
    for claim in claims[:max_claims]:
        try:
            results = await client.search(claim, count=2)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Веб-сверка «%s» не удалась: %s", claim, exc)
            continue
        if not results:
            continue
        lines = [
            f"• {r.title} — {r.description} ({r.url})".strip()
            for r in results[:2]
        ]
        blocks.append(f"Запрос: {claim}\n" + "\n".join(lines))
    if not blocks:
        return ""
    return "<находки_из_интернета>\n" + "\n\n".join(blocks) + "\n</находки_из_интернета>\n"


async def editorial_rewrite(
    client: RewriterClient, *, original: str, link_content: str,
    prompt_name: str, language: str | None,
    on_step: StepCallback | None = None,
) -> EditorialResult:
    """Полный редакционный цикл для одного варианта. Черновик обязателен —
    ошибка на нём пробрасывается (как и в обычном рерайте). Дальше рецензия и
    правка best-effort: сбой оставляет лучший из полученных текстов.

    `on_step` — необязательная трансляция хода наружу (F50): вызывается после
    каждого шага с (стадия, текст). Её сбой не влияет на результат.
    """
    settings = get_settings()
    total_tokens = 0

    # 1. Журналист пишет черновик (обычный рерайт по стилю источника).
    draft_result = await client.rewrite(
        original, prompt_name=prompt_name, link_content=link_content, language=language,
    )
    draft = draft_result.text
    total_tokens += draft_result.total_tokens
    await _emit(on_step, STEP_DRAFT, draft)

    max_rounds = max(0, settings.editorial_max_rounds)
    sources = _build_sources(original, link_content)
    language_line = _language_line(language)
    notes = ""
    rounds_used = 0

    for _ in range(max_rounds):
        # 2. Редактор рецензирует черновик.
        try:
            editor_prompt = resolve_rewrite_template("editor").format(
                sources=sources, draft=draft, language_line=language_line,
            )
            review = await client.rewrite_with_prompt(
                editor_prompt, temperature=_EDITOR_TEMPERATURE,
            )
            total_tokens += review.total_tokens
        except Exception as exc:
            if is_billing_error(exc):
                raise
            logger.warning("Рецензия редактора не удалась (%s) — оставляю черновик", exc)
            break

        approved, critique, claims = _parse_editor_output(review.text)
        if approved:
            notes = _APPROVED_NOTE
            await _emit(on_step, STEP_VERDICT, _APPROVED_NOTE)
            break
        if not critique:
            break  # редактор не сказал ничего внятного — не крутим цикл впустую
        await _emit(on_step, STEP_REVIEW, critique)

        # 3. Веб-сверка спорных фактов (не критично: пусто → правим без находок).
        findings = ""
        if settings.editorial_web_verify_enabled and claims:
            findings = await _web_findings(claims, settings.editorial_web_verify_max_claims)
            if findings:
                await _emit(on_step, STEP_WEB_FINDINGS, findings)

        # 4. Журналист переписывает по замечаниям и находкам.
        try:
            revise_prompt = resolve_rewrite_template("journalist_revise").format(
                sources=sources, draft=draft, editor_notes=critique, web_findings=findings,
            )
            revised = await client.rewrite_with_prompt(revise_prompt)
            total_tokens += revised.total_tokens
        except Exception as exc:
            if is_billing_error(exc):
                raise
            logger.warning("Правка по замечаниям не удалась (%s) — оставляю прошлый вариант", exc)
            notes = critique
            break

        if revised.text.strip():
            draft = revised.text
            await _emit(on_step, STEP_REVISION, draft)
        notes = critique
        rounds_used += 1

    result = EditorialResult(
        text=draft, tokens=total_tokens, rounds_used=rounds_used, notes=notes.strip(),
    )
    # Итоговая строка — она же единственное, что видно в режиме `summary`.
    if rounds_used:
        await _emit(
            on_step, STEP_VERDICT,
            f"Готово: раундов правки {rounds_used}, токенов {total_tokens}.",
        )
    return result
