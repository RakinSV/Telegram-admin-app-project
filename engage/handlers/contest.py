"""Конкурсы: участие, проверка условий, розыгрыш и объявление (F44).

Условия проверяются ДВАЖДЫ — при записи и при розыгрыше. Иначе очевидная
дыра: выполнил условие, записался, тут же отписался от канала и всё равно
участвуешь.

Подписка проверяется здесь, а не в `contests_repo`: это единственное условие,
за ответом на которое надо идти в Bot API, а репозиторий про Telegram знать не
должен.
"""

from __future__ import annotations

from html import escape
from aiogram import Bot, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from tg_repost import contests_repo
from tg_repost.config import get_settings
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)
router = Router(name="contest")

# Статусы, при которых человек считается подписанным на канал/состоящим в чате.
_SUBSCRIBED = frozenset({
    ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER,
})


async def is_subscribed(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Подписан ли пользователь. False при любой ошибке — намеренно строго:
    если бот не админ в проверяемом канале, Telegram не отвечает, и засчитывать
    условие «на всякий случай» значило бы обесценить его."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except TelegramBadRequest as exc:
        logger.warning("Не проверить подписку %s на %s: %s", user_id, chat_id, exc)
        return False
    return member.status in _SUBSCRIBED


async def check_all_conditions(
    bot: Bot, contest: contests_repo.ContestView, user_id: int,
) -> contests_repo.EligibilityResult:
    """Полная проверка: очки и рефералы из БД + подписки через Bot API."""
    local = contests_repo.check_local_conditions(contest, user_id)
    missing = list(local.missing)
    for chat_id in contest.require_subscribed_chat_ids:
        if not await is_subscribed(bot, chat_id, user_id):
            missing.append(f"нужна подписка на чат {chat_id}")
    return contests_repo.EligibilityResult(ok=not missing, missing=missing)


async def handle_contest_start(
    bot: Bot, contest_raw: str, user: object, message: Message,
) -> None:
    """Участие по deep-link `?start=contest_<id>` (зовётся из `start.py`)."""
    try:
        contest_id = int(contest_raw)
    except (TypeError, ValueError):
        return
    contest = contests_repo.get_contest(contest_id)
    if contest is None:
        await message.answer("Конкурс не найден — возможно, ссылка устарела.")
        return

    user_id = getattr(user, "id", 0)
    if not user_id:
        return
    result = await check_all_conditions(bot, contest, user_id)
    if not result.ok:
        await message.answer(
            # Экранируем: бот шлёт с parse_mode=HTML (дефолт в bot.py), и
            # «<» в названии Telegram разбирает как начало тега —
            # сообщение не уходит вовсе, с «can't parse entities».
            f"Пока не получается записать тебя на «{escape(contest.title)}»:\n"
            + "\n".join(f"• {m}" for m in result.missing)
            + "\n\nВыполни условия и нажми на ссылку ещё раз.",
        )
        return

    if contests_repo.join_contest(
        contest_id, user_id,
        username=getattr(user, "username", None),
        full_name=getattr(user, "full_name", None),
    ):
        await message.answer(
            f"✅ Ты участвуешь в «{escape(contest.title)}».\n"
            f"Приз: {escape(contest.prize)}\n"
            f"Итоги: {contest.ends_at:%d.%m.%Y %H:%M} UTC\n\n"
            f"Розыгрыш честный и проверяемый: seed опубликован заранее — "
            f"<code>{contest.draw_seed}</code>",
        )
    else:
        await message.answer("Ты уже участвуешь в этом конкурсе (или он завершён).")


def format_results(contest: contests_repo.ContestView, protocol: dict) -> str:
    """Объявление итогов. Seed и алгоритм — в самом сообщении: проверка не
    должна требовать похода к организатору."""
    winners = protocol.get("winners", [])
    participants = protocol.get("participants", [])
    lines = [
        f"🏁 Итоги конкурса «{contest.title}»",
        f"Приз: {contest.prize}",
        "",
        "Победители: " + ", ".join(f'<a href="tg://user?id={w}">{w}</a>' for w in winners),
        "",
        f"Участников: {len(participants)}",
        f"Seed (опубликован до старта): <code>{protocol.get('seed', '')}</code>",
        f"Алгоритм: {protocol.get('algorithm', '')}",
        "Результат можно перепроверить самостоятельно.",
    ]
    return "\n".join(lines)


async def draw_due_contests(bot: Bot) -> int:
    """Джоба: разыграть конкурсы, у которых вышел срок, и объявить итоги."""
    if not get_settings().contests_enabled:
        return 0
    drawn = 0
    for contest in contests_repo.due_contests():
        # ПОВТОРНАЯ проверка условий на момент розыгрыша: иначе можно было бы
        # подписаться, записаться и сразу отписаться.
        eligible: list[int] = []
        for entry in contests_repo.list_entries(contest.id):
            result = await check_all_conditions(bot, contest, entry.user_id)
            if result.ok:
                eligible.append(entry.user_id)

        protocol = contests_repo.draw_contest(contest.id, eligible_user_ids=eligible)
        if protocol is None:
            continue
        try:
            await bot.send_message(contest.chat_id, format_results(contest, protocol))
        except TelegramBadRequest as exc:
            # Розыгрыш уже проведён и записан — не объявить хуже, чем не
            # разыграть, но переигрывать нельзя: протокол зафиксирован.
            logger.warning("Итоги конкурса %s не объявлены: %s", contest.id, exc)
        drawn += 1
    return drawn
