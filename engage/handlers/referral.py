"""Реферальная программа (F42): персональная ссылка, учёт, лидерборд.

Участник берёт у бота свою ссылку, приводит по ней друзей — и получает очки за
тех, кто РЕАЛЬНО остался. Антинакрутка живёт в `tg_repost/referrals_repo.py`:
здесь только Telegram-сторона.
"""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from tg_repost import referrals_repo
from tg_repost.config import get_settings
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)
router = Router(name="referral")


async def handle_referral_start(
    bot: Bot, inviter_raw: str, invited_user_id: int, chat_id: int,
) -> None:
    """Обработать переход по реферальной ссылке (зовётся из `start.py`).

    Мусорный payload (ссылку могли исказить при копировании) — молча
    игнорируем: человеку всё равно ответят приветствием, а падать из-за чужой
    опечатки незачем.
    """
    del bot
    try:
        inviter_user_id = int(inviter_raw)
    except (TypeError, ValueError):
        logger.info("Реферальная ссылка с нечисловым payload: %r", inviter_raw)
        return
    if referrals_repo.register_referral(inviter_user_id, invited_user_id, chat_id):
        logger.info("Реферал записан: %s → %s", inviter_user_id, invited_user_id)


async def confirm_referrals_job() -> int:
    """Джоба: засчитать рефералов, выдержавших срок."""
    settings = get_settings()
    if not settings.referrals_enabled:
        return 0
    return referrals_repo.confirm_matured_referrals(settings.referral_min_days)


def _format_invite(bot_username: str, user_id: int, stats: referrals_repo.ReferralStats,
                   min_days: int) -> str:
    link = f"https://t.me/{bot_username}?start={referrals_repo.build_referral_payload(user_id)}"
    return (
        "🔗 Твоя личная ссылка для приглашений:\n"
        f"{link}\n\n"
        f"Перешло по ней: {stats.invited}\n"
        f"Вступило: {stats.joined}\n"
        f"Засчитано: {stats.confirmed} (+{stats.points_earned} очков)\n\n"
        f"Приглашение засчитывается, когда человек прожил в группе {min_days} "
        "дн. и написал хотя бы одно сообщение — так награды получают за живых "
        "участников, а не за мультиаккаунты."
    )


@router.message(Command("invite"))
async def cmd_invite(message: Message, bot: Bot) -> None:
    """Выдать участнику его персональную ссылку и статистику."""
    user = message.from_user
    if user is None:
        return
    settings = get_settings()
    if not settings.referrals_enabled:
        await message.answer("Реферальная программа сейчас выключена.")
        return
    me = await bot.get_me()
    stats = referrals_repo.stats_for(user.id)
    await message.answer(
        _format_invite(me.username or "", user.id, stats, settings.referral_min_days),
    )
