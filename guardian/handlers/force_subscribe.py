"""Обязательная подписка на канал (F61).

Подсмотрено у GroupHelp: участник не может писать в группе, пока не подписан
на связанный канал. Прямая воронка «участник группы → подписчик канала»,
которая до сих пор не работала никак.

Механика — один вызов `getChatMember`, платить за неё сторонним ботам не за
что.

ТРИ ВЕЩИ, БЕЗ КОТОРЫХ ЭТО ПРЕВРАЩАЕТСЯ В ОТТАЛКИВАЮЩИЙ БАРЬЕР:

1. **Человеку говорят, что произошло, и дают ссылку.** Молча удалённое
   сообщение выглядит как поломка чата, а не как правило: новичок решит, что
   его забанили ни за что, и уйдёт;
2. **Напоминание не чаще раза в N минут.** Иначе каждое сообщение из
   пяти подряд породит пять одинаковых уведомлений, и это будет спам от
   имени владельца;
3. **Администраторы и доверенные освобождены.** Владелец, забывший
   подписаться на собственный канал, не должен обнаружить, что не может
   писать в своей же группе.

ПРОВЕРКА FAIL-OPEN. Если Bot API не ответил или бот не админ в канале, мы
ПРОПУСКАЕМ сообщение. Тот же принцип, что у AI-фильтра: лучше пропустить
неподписанного, чем перекрыть чат из-за сетевой ошибки.
"""

from __future__ import annotations

import time

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from guardian.config import get_guardian_settings
from guardian.logging_conf import get_logger
from guardian.services import chat_admins

logger = get_logger(__name__)

# Статусы, при которых человек считается подписанным.
_SUBSCRIBED = ("creator", "administrator", "member")

# Пауза между напоминаниями одному человеку.
REMINDER_COOLDOWN_SECONDS = 300
_last_reminder: dict[tuple[int, int], float] = {}


async def is_subscribed(bot: Bot, channel: str | int, user_id: int) -> bool | None:
    """Подписан ли человек. `None` — проверить не удалось.

    `None`, а не `False`: «не знаем» и «не подписан» — разные вещи, и
    вызывающий обязан различать их, иначе сетевая ошибка перекроет чат.
    """
    try:
        member = await bot.get_chat_member(channel, user_id)
    except TelegramBadRequest as exc:
        logger.warning(
            "F61: не удалось проверить подписку %s на %s: %s", user_id, channel, exc,
        )
        return None
    return member.status in _SUBSCRIBED


def _should_remind(chat_id: int, user_id: int) -> bool:
    """Не чаще раза в N минут — иначе пять сообщений дадут пять уведомлений."""
    key = (chat_id, user_id)
    now = time.monotonic()
    last = _last_reminder.get(key)
    if last is not None and now - last < REMINDER_COOLDOWN_SECONDS:
        return False
    _last_reminder[key] = now
    return True


async def enforce(message: Message, bot: Bot) -> bool:
    """Проверить подписку. `True` — сообщение удалено, обработку прекратить.

    Возвращает именно «обработано ли», а не «подписан ли»: вызывающему в
    цепочке фильтров важно только, продолжать ли с этим сообщением.
    """
    settings = get_guardian_settings()
    channel = settings.force_subscribe_channel.strip()
    if not settings.force_subscribe_enabled or not channel:
        return False
    if message.from_user is None or message.from_user.is_bot:
        return False

    user_id = message.from_user.id
    # Администратор группы, забывший подписаться на собственный канал, не
    # должен обнаружить, что не может писать у себя же.
    if await chat_admins.is_chat_admin(bot, message.chat.id, user_id):
        return False

    subscribed = await is_subscribed(bot, channel, user_id)
    if subscribed is None or subscribed:
        # fail-open: не смогли проверить — пропускаем. Перекрыть чат из-за
        # сетевой ошибки хуже, чем пропустить одного неподписанного.
        return False

    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    if _should_remind(message.chat.id, user_id):
        link = channel if channel.startswith("http") else f"https://t.me/{channel.lstrip('@')}"
        try:
            await bot.send_message(
                message.chat.id,
                f"Чтобы писать в этой группе, подпишитесь на канал: {link}\n"
                "После подписки просто отправьте сообщение снова.",
            )
        except TelegramBadRequest as exc:
            logger.warning("F61: не удалось отправить напоминание: %s", exc)

    logger.info("F61: сообщение от %s удалено — нет подписки на %s", user_id, channel)
    return True
