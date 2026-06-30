"""Хэш-дедупликация (F04) — первая линия отсева точных дублей.

Текст нормализуется (нижний регистр, схлопывание пробелов, удаление URL и
пунктуации по краям), затем берётся SHA-256. Семантический дубль-чек через
эмбеддинги — отдельная фича F13 (Фаза 2).
"""

from __future__ import annotations

import hashlib
import re

_WHITESPACE_RE = re.compile(r"\s+")
_URL_RE = re.compile(r"https?://\S+")
# Оставляем буквы/цифры разных алфавитов и пробелы, остальное убираем.
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_text(text: str) -> str:
    """Привести текст к каноничному виду для сравнения дублей."""
    text = text.lower()
    text = _URL_RE.sub(" ", text)
    text = _PUNCT_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def content_hash(text: str) -> str:
    """SHA-256 от нормализованного текста."""
    normalized = normalize_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
