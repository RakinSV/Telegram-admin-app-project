"""Пайплайн фильтров на входящее сообщение группы (G03/G04/G06/G09/G10).

Порядок проверок — от дешёвых к дорогим: trusted-байпас → форварды → флуд →
дубли → ссылки → стоп-слова (`keywords`/`hybrid`) → эвристики+AI (`hybrid`,
только для подозрительных ~20%) → AI на каждое сообщение (`ai`-режим,
дороже всего, поэтому последний и опциональный).
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from guardian.config import GuardianSettings, get_guardian_settings
from guardian.db.models import Member, ModerationLog, TrustedUser
from guardian.db.session import session_scope
from guardian.filters import ai_filter, heuristics
from guardian.filters.flood_filter import FloodFilter
from guardian.filters.keyword_filter import KeywordFilter
from guardian.filters.link_filter import LinkFilter
from guardian.logging_conf import get_logger
from guardian.services import daily_stats_repo
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

# Минимум признаков подозрительности (G10), чтобы передать сообщение в AI —
# см. guardian/filters/heuristics.py. Не вынесено в SETTINGS_GROUPS (веб-
# админка) намеренно — это внутренний параметр алгоритма, не то, что
# оператору обычно нужно тюнить, в отличие от ai_spam_confidence_threshold.
_HYBRID_SUSPICION_THRESHOLD = 2


def _is_trusted(user_id: int, chat_id: int) -> bool:
    with session_scope() as session:
        return (
            session.query(TrustedUser)
            .filter(TrustedUser.user_id == user_id, TrustedUser.chat_id == chat_id)
            .count()
            > 0
        )


def _member_join_date(user_id: int, chat_id: int):
    with session_scope() as session:
        member = (
            session.query(Member)
            .filter(Member.user_id == user_id, Member.chat_id == chat_id)
            .one_or_none()
        )
        return member.join_date if member is not None else None


async def _delete_and_warn(bot: Bot, message: Message, user_id: int, reason: str) -> None:
    """`user_id` берётся аргументом, а не `message.from_user.id` — вызывающий
    (`on_message`) уже проверил `from_user is not None` до вызова, но эта
    проверка в другой функции, mypy не может её учесть."""
    deleted = True
    try:
        await message.delete()
    except TelegramBadRequest as exc:
        deleted = False
        logger.warning(
            "Не удалось удалить сообщение %s в %s: %s",
            message.message_id,
            message.chat.id,
            exc,
        )
    await add_warn(bot, user_id, message.chat.id, reason)
    if deleted:
        # Отдельная запись от того, что уже пишет `add_warn` (action="warn") —
        # нужна для точного счётчика "удалено сообщений" в /stats (G11):
        # не каждый warn сопровождается удалением (например варн за флуд),
        # так что age(warn) != age(deleted_msgs) (найдено при добавлении G11).
        with session_scope() as session:
            session.add(
                ModerationLog(
                    action="delete_msg",
                    user_id=user_id,
                    chat_id=message.chat.id,
                    reason=reason,
                    actor="auto",
                )
            )


async def _ai_check(
    bot: Bot, message: Message, user_id: int, text: str, settings: GuardianSettings
) -> bool:
    """Вернуть True, если сообщение обработано (удалено) — вызывающий код
    должен прекратить дальнейшую обработку."""
    result = await ai_filter.classify(text)
    if result is None:
        return False  # таймаут/ошибка/невалидный ответ — fail-open, пропускаем
    daily_stats_repo.record_ai_call(message.chat.id, result.cost_usd)
    if result.is_spam and result.confidence >= settings.ai_spam_confidence_threshold:
        await _delete_and_warn(bot, message, user_id, f"AI: {result.reason}")
        return True
    return False


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def on_message(message: Message, bot: Bot) -> None:
    settings = get_guardian_settings()
    if message.from_user is None or message.from_user.is_bot:
        return
    # F28: список защищаемых чатов, не одна группа — см. config.py про
    # protected_chat_ids.
    if message.chat.id not in settings.protected_chat_ids:
        return

    user_id = message.from_user.id
    if _is_trusted(user_id, message.chat.id):
        return

    if message.forward_origin is not None and not settings.allow_forwards:
        await _delete_and_warn(bot, message, user_id, "пересланное сообщение (форварды запрещены)")
        return

    if flood_filter.check_flood(message.chat.id, user_id):
        await add_warn(bot, user_id, message.chat.id, "флуд (слишком много сообщений подряд)")
        return

    text = message.text or message.caption or ""
    if text and flood_filter.check_duplicate(message.chat.id, user_id, text):
        await _delete_and_warn(bot, message, user_id, "дублирующееся сообщение подряд")
        return

    is_bad_link, domain = link_filter.check(message, message.chat.id)
    if is_bad_link:
        if settings.strict_mode:
            await _delete_and_warn(bot, message, user_id, f"ссылка на неразрешённый домен: {domain}")
            return
        # G16, soft-режим: ссылки только логируются, не удаляются и не
        # варнятся — см. GUARDIAN_FEATURES.md ("ссылки только логируются
        # (не удаляются)"). Стоп-слова ниже soft-режим НЕ смягчает — по
        # плану G16 они "работают" как обычно в обоих режимах.
        with session_scope() as session:
            session.add(
                ModerationLog(
                    action="link_flagged",
                    user_id=user_id,
                    chat_id=message.chat.id,
                    reason=f"ссылка на неразрешённый домен: {domain} (soft-режим — не удалено)",
                    actor="auto",
                )
            )

    if settings.spam_mode in ("keywords", "hybrid") and text:
        hit, word = keyword_filter.check(text, message.chat.id)
        if hit:
            await _delete_and_warn(bot, message, user_id, f"стоп-слово: {word}")
            return

    if not text:
        return

    if settings.spam_mode == "ai":
        await _ai_check(bot, message, user_id, text, settings)
    elif settings.spam_mode == "hybrid":
        join_date = _member_join_date(user_id, message.chat.id)
        if heuristics.count_suspicion_signals(message, join_date) >= _HYBRID_SUSPICION_THRESHOLD:
            await _ai_check(bot, message, user_id, text, settings)
