"""Антирейд (G14) — детектор всплеска новых участников, НЕЗАВИСИМО на
каждую защищаемую группу (F28: раньше была ровно одна группа, теперь
список `protected_chat_ids` — два защищаемых чата могут словить рейд
одновременно и независимо, нельзя валить их в одно состояние).

Состояние (активен ли рейд-режим, сохранённые права чата) — в памяти
процесса, не в БД, словарь `{chat_id: _RaidState}`: рестарт Guardian ровно
в момент активного рейда — редкий край, приемлемо потерять "заморожено"
через рестарт (тот же выбор, что и `FloodFilter`, см. его docstring).
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


# chat_id -> состояние антирейда ЭТОГО чата (F28, см. docstring модуля).
_states: dict[int, _RaidState] = {}


def _get_state(chat_id: int) -> _RaidState:
    return _states.setdefault(chat_id, _RaidState())


def is_raid_active(chat_id: int) -> bool:
    return _get_state(chat_id).active


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
    state = _get_state(chat_id)
    permissions = state.saved_permissions or ChatPermissions(can_send_messages=True)
    try:
        await bot.set_chat_permissions(chat_id, permissions=permissions)
    except TelegramBadRequest as exc:
        logger.error("Антирейд: не удалось восстановить права чата %s: %s", chat_id, exc)
    state.active = False
    state.saved_permissions = None
    with session_scope() as session:
        # user_id=0 — не про конкретного пользователя, действие над самим
        # чатом; поле в схеме обязательное (см. db/models.py::ModerationLog).
        session.add(ModerationLog(action="raid_end", user_id=0, chat_id=chat_id, actor="auto"))
    logger.info("Антирейд: режим снят, права чата %s восстановлены", chat_id)


def _raid_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    # F28: chat_id закодирован в callback_data — уведомление о рейде должно
    # однозначно указывать, КАКОЙ из НЕСКОЛЬКИХ защищаемых чатов
    # разморозить/оставить в авто-режиме (раньше подразумевалась ровно одна
    # группа — guardian_group_id).
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Разморозить вручную", callback_data=f"raid:unfreeze:{chat_id}",
                ),
                InlineKeyboardButton(
                    text="Продолжить авто", callback_data=f"raid:continue:{chat_id}",
                ),
            ]
        ]
    )


async def _trigger_raid_mode(bot: Bot, chat_id: int, count: int, window_minutes: int) -> None:
    state = _get_state(chat_id)
    try:
        chat = await bot.get_chat(chat_id)
        # ВАЖНО: сохранить ТЕКУЩИЕ права ДО заморозки — иначе восстановление
        # откатится к дефолтным правам Telegram, а не к тем, что реально
        # были настроены в группе (см. GUARDIAN_FEATURES.md G14, п.2).
        state.saved_permissions = chat.permissions
        await bot.set_chat_permissions(chat_id, permissions=_FROZEN_PERMISSIONS)
    except TelegramBadRequest as exc:
        logger.error("Антирейд: не удалось заморозить чат %s: %s", chat_id, exc)
        return
    state.active = True

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
                f"🚨 Рейд-атака в группе {chat_id}! Группа заморожена.\n"
                f"Вступило {count} участников за {window_minutes} мин.",
                reply_markup=_raid_keyboard(chat_id),
            )
        except Exception as exc:  # noqa: BLE001 — уведомление не должно ронять детектор
            logger.warning("Антирейд: не удалось отправить уведомление: %s", exc)


async def check_raid(bot: Bot, now: datetime | None = None) -> None:
    """Периодическая проверка (APScheduler, раз в минуту, см. bot.py) —
    НЕЗАВИСИМО по каждой защищаемой группе (F28, см. docstring модуля).

    `now` — только для тестов (симуляция "прошло N минут" без реального
    сна); в проде всегда `None` → `datetime.now(timezone.utc)`."""
    settings = get_guardian_settings()
    for chat_id in settings.protected_chat_ids:
        # Аудит: изоляция по чату — неожиданное (не TelegramBadRequest,
        # тот уже перехвачен внутри _trigger_raid_mode/_restore_permissions)
        # исключение на одном chat_id не должно обрывать проверку
        # остальных групп в этом же тике; без try/except одна сбойная
        # группа "съедала" бы весь оставшийся список до следующего тика.
        try:
            state = _get_state(chat_id)
            if state.active:
                if _new_members_since(chat_id, settings.raid_cooldown_minutes, now=now) == 0:
                    await _restore_permissions(bot, chat_id)
                continue

            count = _new_members_since(chat_id, settings.raid_join_window_minutes, now=now)
            if count > settings.raid_join_threshold:
                await _trigger_raid_mode(bot, chat_id, count, settings.raid_join_window_minutes)
        except Exception:
            logger.exception("G14: проверка антирейда упала для чата %s", chat_id)


@router.callback_query(F.data.startswith("raid:"))
async def on_raid_callback(callback: CallbackQuery, bot: Bot) -> None:
    from guardian.handlers.admin import _is_admin  # локальный импорт — см. handlers/stats.py про переиспользование

    if callback.message is None or callback.from_user is None:
        await callback.answer()
        return

    # F28: chat_id закодирован в самой кнопке (см. _raid_keyboard) — с
    # несколькими защищаемыми группами нельзя больше брать его из
    # guardian_group_id (единственной группы, которой уже нет).
    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3 or parts[1] not in ("unfreeze", "continue") or not parts[2].lstrip("-").isdigit():
        await callback.answer()
        return
    action, chat_id = parts[1], int(parts[2])

    # ВАЖНО: проверять админство именно в chat_id ИЗ КНОПКИ (чат, над
    # которым выполняется действие), а НЕ в `callback.message.chat.id` —
    # уведомление с кнопками шлётся в `guardian_log_channel_id`, который
    # настраивается независимо и может иметь другой состав админов (найдено
    # security-ревью: иначе админ лог-канала мог разморозить чужую группу
    # посреди активного рейда — актуально и с несколькими группами, см. F28).
    if not await _is_admin(bot, chat_id, callback.from_user.id):
        await callback.answer("Только для администраторов группы.", show_alert=True)
        return

    if action == "unfreeze":
        await _restore_permissions(bot, chat_id)
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
