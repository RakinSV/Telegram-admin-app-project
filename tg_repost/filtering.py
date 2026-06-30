"""Фильтрация постов по ключевым словам (F03).

Возвращает решение: пропустить пост или пометить `filtered_out` с причиной.
Глобальные списки берутся из настроек; per-source списки — задел на будущее.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FilterResult:
    """Результат проверки фильтра."""

    passed: bool
    reason: str | None = None


def check_keywords(
    text: str,
    stop_words: list[str],
    required_words: list[str],
) -> FilterResult:
    """Проверить текст по стоп-словам и обязательным словам.

    - Если встречается любое стоп-слово → не прошёл (filtered_out).
    - Если задан список обязательных слов и ни одно не встречается → не прошёл.
    - Иначе → прошёл.
    """
    haystack = text.lower()

    for stop in stop_words:
        if stop and stop in haystack:
            return FilterResult(passed=False, reason=f"стоп-слово: {stop}")

    if required_words:
        if not any(req and req in haystack for req in required_words):
            return FilterResult(
                passed=False,
                reason="нет ни одного обязательного слова",
            )

    return FilterResult(passed=True)
