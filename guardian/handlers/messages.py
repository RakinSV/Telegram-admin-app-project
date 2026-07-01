"""Пайплайн фильтров на входящее сообщение группы (G03/G04/G06).

Порядок проверок — от дешёвых к дорогим (форварды/флуд/дубли не требуют
парсинга ссылок или обхода стоп-слов): trusted-байпас → форварды → флуд →
дубли → ссылки → стоп-слова. AI-режим (G09/G10) — Фаза G2, здесь ещё нет.
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from guardian.config import get_guardian_settings
from guardian.db.models import TrustedUser
from guardian.db.session import session_scope
from guardian.filters.flood_filter import FloodFilter
from guardian.filters.keyword_filter import KeywordFilter
from guardian.filters.link_filter import LinkFilter
from guardian.logging_conf import get_logger
from guardian.services.warn_system import add_warn

logger = get_logger(__name__)
router = Router(name="messages")

# Синглтоны на процесс — `reload()` вызывается при старте бота (bot.py) и
# после мутирующих команд администратора (/addword, /addomain — handlers/admin.py).
keyword_filter = KeywordFilter()
link_filter = LinkFilter()
_settings = get_guardian_settings()
flood_filter = FloodFilter(
    max_messages=_settings.flood_max_messages,
    window_seconds=_settings.flood_window_seconds,
)


def _is_trusted(user_id: int, chat_id: int) -> bool:
    with session_scope() as session:
        return (
            session.query(TrustedUser)
            .filter(TrustedUser.user_id == user_id, TrustedUser.chat_id == chat_id)
            .count()
            > 0
        )


async def _delete_and_warn(
    bot: Bot, message: Message, user_id: int, reason: str
) -> None:
    """`user_id` берётся аргументом, а не `message.from_user.id` — вызывающий
    (`on_message`) уже проверил `from_user is not None` до вызова, но эта
    проверка в другой функции, mypy не может её учесть."""
    try:
        await message.delete()
    except TelegramBadRequest as exc:
        logger.warning(
            "Не удалось удалить сообщение %s в %s: %s",
            message.message_id,
            message.chat.id,
            exc,
        )
    await add_warn(bot, user_id, message.chat.id, reason)


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def on_message(message: Message, bot: Bot) -> None:
    settings = get_guardian_settings()
    if message.from_user is None or message.from_user.is_bot:
        return
    if message.chat.id != settings.guardian_group_id:
        return

    user_id = message.from_user.id
    if _is_trusted(user_id, message.chat.id):
        return

    if message.forward_origin is not None and not settings.allow_forwards:
        await _delete_and_warn(
            bot, message, user_id, "пересланное сообщение (форварды запрещены)"
        )
        return

    if flood_filter.check_flood(user_id):
        await add_warn(
            bot, user_id, message.chat.id, "флуд (слишком много сообщений подряд)"
        )
        return

    text = message.text or message.caption or ""
    if text and flood_filter.check_duplicate(user_id, text):
        await _delete_and_warn(bot, message, user_id, "дублирующееся сообщение подряд")
        return

    is_bad_link, domain = link_filter.check(message)
    if is_bad_link:
        await _delete_and_warn(
            bot, message, user_id, f"ссылка на неразрешённый домен: {domain}"
        )
        return

    if settings.spam_mode in ("keywords", "hybrid") and text:
        hit, word = keyword_filter.check(text)
        if hit:
            await _delete_and_warn(bot, message, user_id, f"стоп-слово: {word}")
            return
