"""Кэш администраторов чата — общая точка проверки прав.

Жил внутри `handlers/admin.py`, пока был нужен только админ-командам. С
приходом F57 (разметка спорных вердиктов кнопками в лог-канале) проверка
понадобилась и в `handlers/messages.py`, а тот уже импортируется из
`admin.py` — получился цикл. Значит, это не деталь обработчика, а
инфраструктура, и место ей здесь.

Кэш ОДИН на все проверки специально, а не для экономии: два независимых
механизма означали бы, что снятые права администратора перестают
действовать в двух местах в разное время.
"""

from __future__ import annotations

import time

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

# TTL — компромисс между «не долбить API» и «снятые права админа должны
# перестать работать не мгновенно, а в течение TTL». Разумно для чата с
# нечастой сменой модераторов.
_ADMIN_CACHE_TTL_SECONDS = 60
_admin_cache: dict[int, tuple[set[int], float]] = {}


async def get_admin_ids(bot: Bot, chat_id: int) -> set[int]:
    """id администраторов чата. Один вызов Bot API на чат, не на пользователя.

    Раньше каждая команда — в том числе от НЕ-админа, до отказа — дёргала
    `get_chat_member` живьём, что давало любому участнику дешёвый способ
    засыпать Bot API запросами, просто спамя любую /-команду (найдено при
    security-аудите). `get_chat_administrators` возвращает весь список одним
    вызовом.
    """
    cached = _admin_cache.get(chat_id)
    now = time.monotonic()
    if cached is not None and now - cached[1] < _ADMIN_CACHE_TTL_SECONDS:
        return cached[0]
    try:
        admins = await bot.get_chat_administrators(chat_id)
    except TelegramBadRequest:
        # Держим прошлый список: недоступность чата на секунду не повод
        # мгновенно лишить прав всех модераторов.
        return cached[0] if cached is not None else set()
    ids = {admin.user.id for admin in admins}
    _admin_cache[chat_id] = (ids, now)
    return ids


async def is_chat_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Администратор ли пользователь в этом чате."""
    return user_id in await get_admin_ids(bot, chat_id)
