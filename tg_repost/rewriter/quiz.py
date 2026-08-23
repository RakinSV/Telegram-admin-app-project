"""Составитель викторины (F43) — ещё одна LLM-роль поверх того же клиента.

Вопрос делается из УЖЕ проверенного материала: текст статьи извлечён
(trafilatura, F16), факты сверены редактором-фактчекером (F40). Поэтому вопрос
опирается на реальный текст, а не на выдумку модели — то, ради чего вся
редакция и строилась.

Модуль намеренно НЕ знает ни про Telegram, ни про БД: получает текст, отдаёт
разобранный вопрос. Публикацией занимается бот Engage, хранением — quiz_repo.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from tg_repost.rewriter.client import ROLE_QUIZ
from tg_repost.logging_conf import get_logger
from tg_repost.rewriter.client import RewriterClient, resolve_rewrite_template

logger = get_logger(__name__)

# Викторина должна быть точной, а не «творческой»: вопрос обязан опираться на
# текст. Низкая температура — как у редактора-фактчекера (F40).
_QUIZ_TEMPERATURE = 0.2

# Лимиты Telegram для quiz-poll. Больше — API отвергнет весь запрос.
MAX_QUESTION_LEN = 300
MAX_OPTION_LEN = 100
MAX_EXPLANATION_LEN = 200
# Telegram требует от 2 до 10 вариантов; промпт просит 4.
MIN_OPTIONS = 2
MAX_OPTIONS = 10

# Модели любят обрамлять JSON в ```json ... ``` вопреки инструкции.
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class QuizDraft:
    """Готовый вопрос викторины."""

    question: str
    options: list[str]
    correct_index: int
    explanation: str
    tokens: int = 0


def _strip_fence(text: str) -> str:
    return _FENCE_RE.sub("", text.strip())


def parse_quiz_json(raw: str) -> QuizDraft | None:
    """Разобрать ответ модели. None — ответ невалиден.

    Возвращаем None, а не бросаем: невалидный квиз — не повод ронять пайплайн,
    пост уже опубликован и живёт своей жизнью. Просто не будет викторины.
    """
    try:
        data = json.loads(_strip_fence(raw))
    except (json.JSONDecodeError, ValueError):
        logger.warning("Квиз: модель вернула не-JSON")
        return None
    if not isinstance(data, dict):
        return None

    question = str(data.get("question") or "").strip()
    raw_options = data.get("options")
    explanation = str(data.get("explanation") or "").strip()
    if not question or not isinstance(raw_options, list):
        return None

    options = [str(o).strip() for o in raw_options if str(o).strip()]
    if not (MIN_OPTIONS <= len(options) <= MAX_OPTIONS):
        logger.warning("Квиз: вариантов %d — вне допустимого диапазона", len(options))
        return None
    if len(set(options)) != len(options):
        # Дубли среди вариантов означают, что «правильный» неотличим от
        # «неправильного» — такой вопрос хуже отсутствия вопроса.
        logger.warning("Квиз: варианты повторяются")
        return None

    raw_index = data.get("correct_index")
    if raw_index is None:
        return None
    try:
        correct_index = int(raw_index)
    except (TypeError, ValueError):
        return None
    if not 0 <= correct_index < len(options):
        logger.warning("Квиз: correct_index=%s вне списка вариантов", correct_index)
        return None

    # Обрезаем под лимиты Telegram, а не отбраковываем: длинный вопрос лучше
    # обрезать, чем потерять весь квиз.
    return QuizDraft(
        question=question[:MAX_QUESTION_LEN],
        options=[o[:MAX_OPTION_LEN] for o in options],
        correct_index=correct_index,
        explanation=explanation[:MAX_EXPLANATION_LEN],
    )


async def generate_quiz(client: RewriterClient, source_text: str) -> QuizDraft | None:
    """Составить викторину по материалу. None при любой проблеме."""
    if not source_text.strip():
        return None
    prompt = resolve_rewrite_template("quiz").format(source=source_text)
    try:
        result = await client.rewrite_with_prompt(
            prompt, temperature=_QUIZ_TEMPERATURE, role=ROLE_QUIZ,
        )
    except Exception as exc:  # noqa: BLE001
        # Викторина — необязательная надстройка над постом: её сбой не должен
        # ничего ломать (в отличие от рерайта, где ошибка значима).
        logger.warning("Не удалось составить квиз: %s", exc)
        return None

    draft = parse_quiz_json(result.text)
    if draft is None:
        return None
    return QuizDraft(
        question=draft.question, options=draft.options,
        correct_index=draft.correct_index, explanation=draft.explanation,
        tokens=result.total_tokens,
    )
