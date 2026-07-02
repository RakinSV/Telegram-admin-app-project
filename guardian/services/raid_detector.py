"""Антирейд (G14) — детектор всплеска новых участников.

Состояние (активен ли рейд-режим, сохранённые права чата) — в памяти
процесса, не в БД: рестарт Guardian ровно в момент активного рейда — редкий
край, приемлемо потерять "заморожено" через рестарт (тот же выбор, что и
`FloodFilter`, см. его docstring).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from guardian.config import get_guardian_settings
from guardian.db.models import Member, ModerationLog
from guardian.db.session import session_scope
from guardian.logging_conf import get_logger

logger = get_logger(__name__)
router = Router(name="raid")

_FROZEN_PERMISSIONS = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
    can_change_info=False,
    can_invite_users=False,
    can_pin_messages=False,
)


@dataclass
class _RaidState:
    active: bool = False
    saved_permissions: ChatPermissions | None = None


_state = _RaidState()


def is_raid_active() -> bool:
    return _state.active


def _new_members_since(chat_id: int, minutes: int, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(minutes=minutes)
    with session_scope() as session:
        return (
            session.query(Member)
            .filter(Member.chat_id == chat_id, Member.join_date >= since)
            .count()
        )


async def _restore_permissions(bot: Bot, chat_id: int) -> None:
    permissions = _state.saved_permissions or ChatPermissions(can_send_messages=True)
    try:
        await bot.set_chat_permissions(chat_id, permissions=permissions)
    except TelegramBadRequest as exc:
        logger.error("Антирейд: не удалось восстановить права чата %s: %s", chat_id, exc)
    _state.active = False
    _state.saved_permissions = None
    with session_scope() as session:
        # user_id=0 — не про конкретного пользователя, действие над самим
        # чатом; поле в схеме обязательное (см. db/models.py::ModerationLog).
        session.add(ModerationLog(action="raid_end", user_id=0, chat_id=chat_id, actor="auto"))
    logger.info("Антирейд: режим снят, права чата %s восстановлены", chat_id)


def _raid_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Разморозить вручную", callback_data="raid:unfreeze"),
                InlineKeyboardButton(text="Продолжить авто", callback_data="raid:continue"),
            ]
        ]
    )


async def _trigger_raid_mode(bot: Bot, chat_id: int, count: int, window_minutes: int) -> None:
    try:
        chat = await bot.get_chat(chat_id)
        # ВАЖНО: сохранить ТЕКУЩИЕ права ДО заморозки — иначе восстановление
        # откатится к дефолтным правам Telegram, а не к тем, что реально
        # были настроены в группе (см. GUARDIAN_FEATURES.md G14, п.2).
        _state.saved_permissions = chat.permissions
        await bot.set_chat_permissions(chat_id, permissions=_FROZEN_PERMISSIONS)
    except TelegramBadRequest as exc:
        logger.error("Антирейд: не удалось заморозить чат %s: %s", chat_id, exc)
        return
    _state.active = True

    with session_scope() as session:
        session.add(
            ModerationLog(
                action="raid_detected",
                user_id=0,
                chat_id=chat_id,
                reason=f"{count} участников за {window_minutes} мин.",
                actor="auto",
            )
        )
    logger.warning("Антирейд: обнаружен рейд в %s (%d участников за %d мин.) — чат заморожен", chat_id, count, window_minutes)

    settings = get_guardian_settings()
    if settings.guardian_log_channel_id:
        try:
            await bot.send_message(
                settings.guardian_log_channel_id,
                f"🚨 Рейд-атака! Группа заморожена.\n"
                f"Вступило {count} участников за {window_minutes} мин.",
                reply_markup=_raid_keyboard(),
            )
        except Exception as exc:  # noqa: BLE001 — уведомление не должно ронять детектор
            logger.warning("Антирейд: не удалось отправить уведомление: %s", exc)


async def check_raid(bot: Bot, now: datetime | None = None) -> None:
    """Периодическая проверка (APScheduler, раз в минуту, см. bot.py).

    `now` — только для тестов (симуляция "прошло N минут" без реального
    сна); в проде всегда `None` → `datetime.now(timezone.utc)`."""
    settings = get_guardian_settings()
    if not settings.guardian_group_id:
        return
    chat_id = settings.guardian_group_id

    if _state.active:
        if _new_members_since(chat_id, settings.raid_cooldown_minutes, now=now) == 0:
            await _restore_permissions(bot, chat_id)
        return

    count = _new_members_since(chat_id, settings.raid_join_window_minutes, now=now)
    if count > settings.raid_join_threshold:
        await _trigger_raid_mode(bot, chat_id, count, settings.raid_join_window_minutes)


@router.callback_query(F.data.in_({"raid:unfreeze", "raid:continue"}))
async def on_raid_callback(callback: CallbackQuery, bot: Bot) -> None:
    from guardian.handlers.admin import _is_admin  # локальный импорт — см. handlers/stats.py про переиспользование

    if callback.message is None or callback.from_user is None:
        await callback.answer()
        return
    settings = get_guardian_settings()
    # ВАЖНО: проверять админство именно в `guardian_group_id` (чат, над
    # которым выполняется действие), а НЕ в `callback.message.chat.id` —
    # уведомление с кнопками шлётся в `guardian_log_channel_id`, который
    # настраивается независимо и может иметь другой состав админов (найдено
    # security-ревью: иначе админ лог-канала мог разморозить чужую группу
    # посреди активного рейда).
    if not settings.guardian_group_id or not await _is_admin(
        bot, settings.guardian_group_id, callback.from_user.id
    ):
        await callback.answer("Только для администраторов группы.", show_alert=True)
        return

    if callback.data == "raid:unfreeze":
        await _restore_permissions(bot, settings.guardian_group_id)
        await callback.answer("Группа разморожена.")
        suffix = "\n\n✅ Разморожено вручную."
    else:
        await callback.answer("Ок, продолжаю следить автоматически.")
        suffix = "\n\n⏳ Продолжаю в авто-режиме."

    # `callback.message` может быть `InaccessibleMessage` (>48ч старое —
    # Telegram больше не отдаёт его содержимое, только id) — тогда просто не
    # редактируем текст, само действие (разморозка/продолжение) выше уже
    # выполнено независимо от этого.
    if isinstance(callback.message, Message):
        await callback.message.edit_text((callback.message.text or "") + suffix)
