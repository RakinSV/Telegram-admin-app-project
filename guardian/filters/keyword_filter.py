"""Фильтр стоп-слов (G03) — режим `keywords`, без LLM.

Нормализация текста перед сравнением намеренно агрессивная (используется
ТОЛЬКО для сравнения со стоп-словами, не меняет отображаемый пользователю
текст): убирает типовые приёмы обхода фильтра — латиница вместо кириллицы,
zero-width символы, буквы через разделители («к-у-п-и-т-ь»)."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from guardian.db.models import StopWord

# Латинские "омоглифы" кириллических букв, которыми часто маскируют
# стоп-слова (к0д, зaработок и т.п.).
_HOMOGLYPHS = str.maketrans(
    {
        "a": "а",
        "e": "е",
        "o": "о",
        "p": "р",
        "c": "с",
        "x": "х",
        "y": "у",
        "A": "А",
        "E": "Е",
        "O": "О",
        "P": "Р",
        "C": "С",
        "X": "Х",
        "Y": "У",
        "0": "о",
    }
)

# ZERO WIDTH SPACE (U+200B) / NON-JOINER (U+200C) / JOINER (U+200D) /
# WORD JOINER (U+2060) / BOM (U+FEFF) — невидимые символы, которыми
# разбивают стоп-слово, чтобы обмануть substring-поиск.
_ZERO_WIDTH_RE = re.compile("[​‌‍⁠﻿]")
_LETTER_SEPARATOR_RE = re.compile(r"(?<=\w)[-_.*~^]+(?=\w)", re.UNICODE)
_MULTI_SPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    text = text.translate(_HOMOGLYPHS)
    text = _ZERO_WIDTH_RE.sub("", text)
    text = _LETTER_SEPARATOR_RE.sub("", text)
    text = text.lower()
    text = _MULTI_SPACE_RE.sub(" ", text).strip()
    return text


class KeywordFilter:
    def __init__(self) -> None:
        self._words: set[str] = set()

    def reload(self, session: Session) -> None:
        """Перечитать стоп-слова из БД в память (O(1)-проверка на сообщение)."""
        self._words = {row.word.lower() for row in session.query(StopWord).all()}

    def check(self, text: str) -> tuple[bool, str | None]:
        """Вернуть (найден_ли_стоп-слово, само_слово)."""
        if not text or not self._words:
            return False, None
        normalized = normalize(text)
        for word in self._words:
            if word in normalized:
                return True, word
        return False, None
