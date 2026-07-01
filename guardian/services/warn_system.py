"""Система варнов и эскалации (G05) — единая точка входа для всех
фильтров и ручных команд администратора (`/warn`).

Эскалация проверяется как «наивысший достигнутый порог», не точное
равенство — устойчиво к изменению порогов через `/setwarn` (G13) между
варнами одного пользователя: варн, поднявший счётчик сразу выше
`warn_threshold_ban`, забанит, а не тихо смутит по устаревшему порогу.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import ChatPermissions

from guardian.config import get_guardian_settings
from guardian.db.models import Member, ModerationLog, Warning
from guardian.db.session import session_scope
from guardian.logging_conf import get_logger
from guardian.services.log_channel import log_action

logger = get_logger(__name__)


async def add_warn(
    bot: Bot, user_id: int, chat_id: int, reason: str, issued_by: str = "auto"
) -> int:
    """Выдать варн, применить эскалацию, вернуть новый `warn_count`."""
    settings = get_guardian_settings()
    now = datetime.now(timezone.utc)

    with session_scope() as session:
        member = (
            session.query(Member)
            .filter(Member.user_id == user_id, Member.chat_id == chat_id)
            .one_or_none()
        )
        if member is None:
            member = Member(user_id=user_id, chat_id=chat_id, is_verified=True)
            session.add(member)
            session.flush()
        member.warn_count += 1
        member.last_warn_date = now
        warn_count = member.warn_count
        session.add(
            Warning(
                user_id=user_id, chat_id=chat_id, reason=reason, issued_by=issued_by
            )
        )
        session.add(
            ModerationLog(
                action="warn",
                user_id=user_id,
                chat_id=chat_id,
                reason=reason,
                actor=issued_by,
            )
        )

    await log_action(
        bot,
        "warn",
        user_id=user_id,
        chat_id=chat_id,
        reason=f"{reason} ({warn_count}/{settings.warn_threshold_ban})",
    )

    if warn_count >= settings.warn_threshold_ban:
        await _ban(bot, user_id, chat_id, reason)
    elif warn_count >= settings.warn_threshold_kick:
        await _kick(bot, user_id, chat_id, reason)
    elif warn_count >= settings.warn_threshold_mute:
        await _mute(bot, user_id, chat_id, reason, settings.mute_duration_hours)

    return warn_count


async def _mute(bot: Bot, user_id: int, chat_id: int, reason: str, hours: int) -> None:
    until = datetime.now(timezone.utc) + timedelta(hours=hours)
    try:
        await bot.restrict_chat_member(
            chat_id,
            user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
    except TelegramBadRequest as exc:
        logger.warning("Не удалось замутить %s в %s: %s", user_id, chat_id, exc)
        return
    with session_scope() as session:
        session.add(
            ModerationLog(
                action="mute",
                user_id=user_id,
                chat_id=chat_id,
                reason=reason,
                actor="auto",
            )
        )
    await log_action(
        bot,
        "mute",
        user_id=user_id,
        chat_id=chat_id,
        reason=f"{reason} (до {until:%H:%M UTC})",
    )


async def _kick(bot: Bot, user_id: int, chat_id: int, reason: str) -> None:
    try:
        await bot.ban_chat_member(chat_id, user_id)
        await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
    except TelegramBadRequest as exc:
        logger.warning("Не удалось кикнуть %s из %s: %s", user_id, chat_id, exc)
        return
    with session_scope() as session:
        session.add(
            ModerationLog(
                action="kick",
                user_id=user_id,
                chat_id=chat_id,
                reason=reason,
                actor="auto",
            )
        )
    await log_action(bot, "kick", user_id=user_id, chat_id=chat_id, reason=reason)


async def _ban(bot: Bot, user_id: int, chat_id: int, reason: str) -> None:
    try:
        await bot.ban_chat_member(chat_id, user_id)
    except TelegramBadRequest as exc:
        logger.warning("Не удалось забанить %s в %s: %s", user_id, chat_id, exc)
        return
    with session_scope() as session:
        member = (
            session.query(Member)
            .filter(Member.user_id == user_id, Member.chat_id == chat_id)
            .one_or_none()
        )
        if member is not None:
            member.is_banned = True
        session.add(
            ModerationLog(
                action="ban",
                user_id=user_id,
                chat_id=chat_id,
                reason=reason,
                actor="auto",
            )
        )
    await log_action(bot, "ban", user_id=user_id, chat_id=chat_id, reason=reason)


def reset_expired_warns() -> int:
    """TTL-сброс (G05): раз в сутки (см. guardian/scheduler.py) обнулить
    `warn_count` у участников, чей последний варн старше `warn_ttl_days`.
    Возвращает число сброшенных участников."""
    settings = get_guardian_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.warn_ttl_days)
    with session_scope() as session:
        members = (
            session.query(Member)
            .filter(
                Member.warn_count > 0,
                Member.last_warn_date.is_not(None),
                Member.last_warn_date < cutoff,
            )
            .all()
        )
        for member in members:
            member.warn_count = 0
        return len(members)
