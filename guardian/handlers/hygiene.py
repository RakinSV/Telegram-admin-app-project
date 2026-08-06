"""Служебная гигиена группы (F48): мелочи, отсутствие которых раздражает.

Три вещи, которые владельцы групп делают руками каждый день:
1. Чистка служебных сообщений («вошёл в группу», «закрепил сообщение») —
   в активной группе они забивают ленту сильнее самого общения.
2. Ночной режим: на ночь группа закрывается (или включается медленный режим),
   утром открывается — иначе спам ловится только утром, а читают его ночью.
3. Напоминание правил по расписанию — правила в закрепе никто не открывает.

Пункты 2 и 3 живут джобами в `bot.py`, здесь — хендлер служебных сообщений и
функции, которые эти джобы зовут (чтобы их можно было тестировать без
планировщика).
"""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import ChatPermissions, Message

from guardian.config import get_guardian_settings
from guardian.logging_conf import get_logger

logger = get_logger(__name__)
router = Router(name="hygiene")

# Служебные события, которые Telegram кладёт в чат отдельными сообщениями.
# Список намеренно НЕ включает `pinned_message`, если владелец сам закрепляет
# важное: пометка о закрепе — единственный способ участнику узнать о нём в
# ленте. Управляется отдельной настройкой.
_JOIN_LEAVE_FIELDS = ("new_chat_members", "left_chat_member")
_OTHER_SERVICE_FIELDS = (
    "new_chat_title", "new_chat_photo", "delete_chat_photo",
    "group_chat_created", "supergroup_chat_created", "channel_chat_created",
    "message_auto_delete_timer_changed", "video_chat_started",
    "video_chat_ended", "video_chat_participants_invited",
)


def _is_protected(chat_id: int) -> bool:
    return chat_id in get_guardian_settings().protected_chat_ids


def _service_kind(message: Message) -> str | None:
    """Какого рода это служебное сообщение (или None — обычное)."""
    if any(getattr(message, field, None) for field in _JOIN_LEAVE_FIELDS):
        return "join_leave"
    if getattr(message, "pinned_message", None):
        return "pinned"
    if any(getattr(message, field, None) for field in _OTHER_SERVICE_FIELDS):
        return "other"
    return None


@router.message()
async def on_service_message(message: Message, bot: Bot) -> None:
    """Удалить служебное сообщение, если для этого чата так настроено.

    Хендлер намеренно регистрируется ПОСЛЕ `messages.router`: обычные
    сообщения должны сначала пройти антиспам, а сюда доходит только то, что
    никто не разобрал. Возврат без действия для не-служебных сообщений
    обязателен — иначе мы бы глушили обычное общение.
    """
    kind = _service_kind(message)
    if kind is None or not _is_protected(message.chat.id):
        return

    settings = get_guardian_settings()
    if kind == "join_leave" and not settings.delete_join_leave_messages:
        return
    if kind == "pinned" and not settings.delete_pin_notifications:
        return
    if kind == "other" and not settings.delete_service_messages:
        return

    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except TelegramBadRequest as exc:
        # Сообщение старше 48 часов Bot API удалять не даёт, и это не повод
        # шуметь ошибкой: чистка — гигиена, а не критичная операция.
        logger.debug("Служебное сообщение не удалено (%s): %s", kind, exc)


# --- Ночной режим (зовётся джобой из bot.py) ---

# Права «только чтение»: участники не могут писать вообще ничего.
_NIGHT_PERMISSIONS = ChatPermissions(
    can_send_messages=False, can_send_other_messages=False,
    can_send_polls=False, can_add_web_page_previews=False,
)
# Обычный режим: то, что разрешено большинству групп по умолчанию. Telegram не
# даёт «вернуть как было» — прошлые права он не хранит, поэтому набор задаётся
# явно (см. предупреждение в описании настройки).
_DAY_PERMISSIONS = ChatPermissions(
    can_send_messages=True, can_send_other_messages=True,
    can_send_polls=True, can_add_web_page_previews=True,
    can_invite_users=True,
)


async def set_night_mode(bot: Bot, chat_id: int, *, closed: bool) -> bool:
    """Закрыть/открыть чат. False — не получилось (нет прав у бота)."""
    try:
        await bot.set_chat_permissions(
            chat_id, _NIGHT_PERMISSIONS if closed else _DAY_PERMISSIONS,
        )
    except TelegramBadRequest as exc:
        logger.warning(
            "Не удалось %s чат %s: %s", "закрыть" if closed else "открыть", chat_id, exc,
        )
        return False
    logger.info("Чат %s %s (ночной режим)", chat_id, "закрыт" if closed else "открыт")
    return True


def is_night_now(hour: int, start: int, end: int) -> bool:
    """Попадает ли час в ночной интервал. Интервал через полночь (23→7) —
    норма, поэтому сравнение не может быть простым `start <= hour < end`."""
    if start == end:
        return False
    return start <= hour < end if start <= end else hour >= start or hour < end


async def send_rules_reminder(bot: Bot, chat_id: int, text: str) -> bool:
    """Напомнить правила. Пустой текст — не шлём (лучше молчать, чем слать
    пустое напоминание)."""
    if not text.strip():
        return False
    try:
        await bot.send_message(chat_id, text, disable_notification=True)
    except TelegramBadRequest as exc:
        logger.warning("Напоминание правил не отправлено в %s: %s", chat_id, exc)
        return False
    return True
