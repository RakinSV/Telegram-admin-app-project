"""Эвристики подозрительности без LLM (G10, часть гибридного режима).

2+ признака → сообщение передаётся в AI-классификатор (`ai_filter.py`);
меньше — AI не вызывается (экономия, см. GUARDIAN.md про latency/стоимость
AI-режима). Ни один признак сам по себе не приводит к действию — это только
фильтр "стоит ли тратить AI-вызов", а не решение об удалении."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

_PRICE_RE = re.compile(r"\d+\s?(?:₽|\$|руб|usd|доллар)", re.IGNORECASE)
_DM_PHRASES = (
    "напиши в лс",
    "напишите в лс",
    "пиши в личку",
    "пишите в личку",
    "пиши в директ",
    "пишите в директ",
    "подробности в профиле",
    "детали в профиле",
    "все детали в профиле",
)
# ZERO WIDTH SPACE/NON-JOINER/JOINER, WORD JOINER, BOM — тот же набор, что и
# в keyword_filter.py (см. его комментарий), здесь отдельная копия
# намеренно — три похожие строки проще, чем тянуть приватный символ из
# другого модуля ради одной regex.
_ZERO_WIDTH_RE = re.compile("[​‌‍⁠﻿]")
_NEW_MEMBER_THRESHOLD = timedelta(days=7)


def count_suspicion_signals(message: Any, member_join_date: datetime | None) -> int:
    """Сколько признаков подозрительности сработало (0-5)."""
    text = getattr(message, "text", None) or getattr(message, "caption", None) or ""
    signals = 0

    if _PRICE_RE.search(text):
        signals += 1
    if any(phrase in text.lower() for phrase in _DM_PHRASES):
        signals += 1
    if _ZERO_WIDTH_RE.search(text):
        signals += 1
    if getattr(message, "forward_origin", None) is not None:
        signals += 1
    if member_join_date is not None:
        now = datetime.now(timezone.utc)
        join_date = member_join_date
        if join_date.tzinfo is None:
            join_date = join_date.replace(tzinfo=timezone.utc)
        if now - join_date < _NEW_MEMBER_THRESHOLD:
            signals += 1

    return signals
