"""Работа с длиной текста в мере Telegram — общая для всех отправителей.

Вынесено из `moderation_bot.py`, когда те же правила понадобились трансляции
редакционного диалога (F50, `telegram/newsroom.py`): дублировать разбор
суррогатных пар в двух местах — гарантированно разъехавшиеся редакции.
"""

from __future__ import annotations


def tg_len(text: str) -> int:
    """Длина строки так, как её считает Telegram, — в UTF-16 code units.

    Эмодзи вне BMP занимают ДВЕ единицы, поэтому подпись из 1000 «питоновских»
    символов с эмодзи спокойно перебирает лимит в 1024 и API отвечает
    `Message caption is too long`. Считать `len()` тут недостаточно.
    """
    return len(text.encode("utf-16-le")) // 2


def clip(text: str, budget: int) -> str:
    """Обрезать до `budget` единиц в мере Telegram, не разорвав эмодзи."""
    if budget <= 0:
        return ""
    if tg_len(text) <= budget:
        return text
    raw = text.encode("utf-16-le")[: budget * 2]
    while raw:
        try:
            return raw.decode("utf-16-le")
        except UnicodeDecodeError:
            raw = raw[:-2]  # отрезали половину суррогатной пары — сдаём назад
    return ""
