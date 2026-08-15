"""Зачистка после рейда и репорты от участников (F58).

Две команды, закрывающие разные дыры, но обе про одно: между «что-то
происходит» и «модератор об этом узнал» не должно быть человека с мышкой.

`/purge` — подсмотрено у Rose. После рейда чат чистится вручную,
сообщение за сообщением; детектор рейда у нас есть, а инструмента убрать
последствия не было.

`/report` — подсмотрено у Combot. Участник видит спам раньше фильтра, но
без прав модератора сказать об этом ему некуда.

ОГРАНИЧЕНИЯ TELEGRAM, КОТОРЫЕ ОПРЕДЕЛИЛИ ДИЗАЙН:

* Bot API не умеет перечислять сообщения чата. Значит `/purge` работает
  по ДИАПАЗОНУ id: от того, на что ответили, до самой команды. Часть id в
  диапазоне не существует или уже удалена — это нормально, ошибки по
  отдельным сообщениям глотаются;
* бот не может удалять сообщения старше 48 часов. Поэтому «зачистить всё
  за прошлую неделю» невозможно в принципе, и обещать это нельзя;
* диапазон ограничен сверху: ответ на сообщение месячной давности иначе
  превратился бы в тысячи бесполезных запросов к API.
"""

from __future__ import annotations

import time

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from guardian.config import get_guardian_settings
from guardian.db.models import ModerationLog
from guardian.db.session import session_scope
from guardian.logging_conf import get_logger
from guardian.services import chat_admins, log_channel

logger = get_logger(__name__)
router = Router(name="purge_report")

# Потолок на диапазон зачистки. Ответ на старое сообщение иначе означал бы
# тысячи запросов к API ради сообщений, которых давно нет.
MAX_PURGE = 200

# Сколько ждать между репортами от одного человека. Без паузы недовольный
# участник забьёт лог-канал жалобами на одного и того же оппонента, и
# модератор перестанет читать канал целиком.
REPORT_COOLDOWN_SECONDS = 60
_last_report: dict[int, float] = {}


@router.message(Command("purge"))
async def cmd_purge(message: Message, bot: Bot) -> None:
    """Удалить сообщения от отвеченного до текущего включительно."""
    if message.from_user is None:
        return
    settings = get_guardian_settings()
    if message.chat.id not in settings.protected_chat_ids:
        return
    if not await chat_admins.is_chat_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("Команда доступна только администраторам группы.")
        return

    if message.reply_to_message is None:
        await message.reply(
            "Ответь этой командой на первое сообщение, которое надо удалить.\n"
            "Всё от него до /purge будет вычищено. "
            f"За раз — не больше {MAX_PURGE} сообщений, и только за последние "
            "48 часов: сообщения старше Telegram боту удалять не даёт."
        )
        return

    start = message.reply_to_message.message_id
    end = message.message_id
    if end - start > MAX_PURGE:
        await message.reply(
            f"Слишком большой диапазон: {end - start} сообщений при пределе "
            f"{MAX_PURGE}. Ответь на сообщение поближе."
        )
        return

    deleted = 0
    for message_id in range(start, end + 1):
        try:
            await bot.delete_message(message.chat.id, message_id)
            deleted += 1
        except TelegramBadRequest:
            # Сообщения нет, оно чужое или старше 48 часов — рядовой случай
            # при работе по диапазону, а не сбой.
            continue

    with session_scope() as session:
        session.add(
            ModerationLog(
                action="purge",
                user_id=message.from_user.id,
                chat_id=message.chat.id,
                reason=f"диапазон {start}–{end}, удалено {deleted}",
                actor=str(message.from_user.id),
            )
        )
    await log_channel.log_action(
        bot, "purge", user_id=message.from_user.id, chat_id=message.chat.id,
        reason=f"удалено {deleted} из {end - start + 1}",
    )
    logger.info(
        "F58: purge в %s: удалено %d из %d", message.chat.id, deleted, end - start + 1,
    )


@router.message(Command("report"))
async def cmd_report(message: Message, bot: Bot) -> None:
    """Жалоба участника на сообщение — уходит модераторам в лог-канал."""
    if message.from_user is None:
        return
    settings = get_guardian_settings()
    if message.chat.id not in settings.protected_chat_ids:
        return

    # Саму команду убираем всегда: она не должна висеть в чате и тем более
    # привлекать внимание к сообщению, на которое жалуются.
    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except TelegramBadRequest:
        pass

    if message.reply_to_message is None:
        return

    now = time.monotonic()
    last = _last_report.get(message.from_user.id)
    if last is not None and now - last < REPORT_COOLDOWN_SECONDS:
        return
    _last_report[message.from_user.id] = now

    target = message.reply_to_message
    author = target.from_user
    if author is None or author.is_bot:
        return

    await log_channel.log_action(
        bot, "report", user_id=author.id, chat_id=message.chat.id,
        reason=f"жалоба от id{message.from_user.id}",
        username=author.username,
        message_text=target.text or target.caption or "(без текста)",
        inline_kb=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="🗑 Удалить",
                callback_data=f"rp:del:{message.chat.id}:{target.message_id}",
            ),
            InlineKeyboardButton(text="✅ Ничего", callback_data="rp:skip"),
        ]]),
    )
    logger.info(
        "F58: репорт от %s на сообщение %s", message.from_user.id, target.message_id,
    )


@router.callback_query(F.data.startswith("rp:"))
async def on_report_decision(callback: CallbackQuery, bot: Bot) -> None:
    """Решение модератора по жалобе.

    Права проверяются по ИСХОДНОМУ чату, а не по лог-каналу: кнопки живут в
    канале, но решение касается группы, и админом надо быть именно там.
    """
    assert callback.data is not None
    parts = callback.data.split(":")

    if parts[1] == "skip":
        if isinstance(callback.message, Message):
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except TelegramBadRequest:
                pass
        await callback.answer("Оставлено как есть.")
        return

    if len(parts) != 4 or not parts[3].isdigit():
        await callback.answer()
        return
    chat_id, message_id = int(parts[2]), int(parts[3])

    if not await chat_admins.is_chat_admin(bot, chat_id, callback.from_user.id):
        await callback.answer(
            "Решение принимает администратор группы.", show_alert=True,
        )
        return

    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramBadRequest:
        await callback.answer("Сообщение уже удалено или слишком старое.", show_alert=True)
        return

    with session_scope() as session:
        session.add(
            ModerationLog(
                action="delete_msg",
                user_id=callback.from_user.id,
                chat_id=chat_id,
                reason="по жалобе участника",
                actor=str(callback.from_user.id),
            )
        )
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
    await callback.answer("Удалено.")
