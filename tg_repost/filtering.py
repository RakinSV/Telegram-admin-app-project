"""Фильтрация постов по ключевым словам (F03 + F54).

Возвращает решение: пропустить пост или пометить `filtered_out` с причиной.
Списки берутся из глобальных настроек и, если заданы, из самого источника
(F54) — см. `resolve_filters`.
"""

from __future__ import annotations

from dataclasses import dataclass

from tg_repost.db.models import Source


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


def parse_words(raw: str | None) -> list[str] | None:
    """CSV из настройки источника → список слов в нижнем регистре.

    `None` на входе означает «источник ничего не переопределяет» и возвращается
    как `None`, а не как пустой список. Разница существенная: пустой список —
    это ЯВНОЕ «требований нет», и для обязательных слов он снимает требование
    совсем, тогда как `None` велит взять глобальный список.
    """
    if raw is None:
        return None
    return [w.strip().lower() for w in raw.split(",") if w.strip()]


def resolve_filters(
    source: Source | None,
    global_stop: list[str],
    global_required: list[str],
) -> tuple[list[str], list[str]]:
    """Итоговые списки для конкретного источника (F54).

    Стоп-слова СКЛАДЫВАЮТСЯ с глобальными, обязательные — ЗАМЕЩАЮТ их.
    Асимметрия намеренная и следует из того, как работает сам фильтр:

    * стоп-слово отсекает пост при любом совпадении, поэтому объединение
      делает правила строже. Позволить источнику молча отключить глобальную
      защиту опаснее, чем оставить лишнее ограничение;
    * обязательные слова срабатывают по «хотя бы одному», поэтому объединение
      их не ужесточило бы, а ОСЛАБИЛО: чем длиннее список, тем больше постов
      проходит. Замещение даёт ленте её собственную тему — ровно то, ради
      чего фича и делалась.
    """
    if source is None:
        return global_stop, global_required

    own_stop = parse_words(source.filter_stop_words)
    own_required = parse_words(source.filter_required_words)

    stop = global_stop if own_stop is None else [*global_stop, *own_stop]
    required = global_required if own_required is None else own_required
    return stop, required
