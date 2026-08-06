"""`/start` с deep-link — точка входа участника в Engage.

Telegram позволяет привести человека в бота ссылкой `t.me/<bot>?start=PAYLOAD`
(payload до 64 символов), и бот получает этот payload первым же сообщением.
Это фундамент сразу трёх фич:
  • F42 рефералы   — `ref_<user_id>`: кто пригласил;
  • F44 конкурсы   — `contest_<id>`: участие по кнопке из поста;
  • F47 предложка  — `suggest`: сразу открыть приём поста.

Здесь только разбор payload и маршрутизация: сами фичи подключаются
обработчиками ниже по мере реализации. Неизвестный payload — НЕ ошибка:
ссылку могли скопировать из старого поста, человеку надо ответить по-людски,
а не молчать.
"""

from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message

from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)
router = Router(name="start")

# Префиксы deep-link. Отделяются ПЕРВЫМ подчёркиванием: сам payload может
# содержать подчёркивания (например, base64-подобные идентификаторы).
PAYLOAD_REFERRAL = "ref"
PAYLOAD_CONTEST = "contest"
PAYLOAD_SUGGEST = "suggest"

_WELCOME = (
    "Привет! Я помогаю с активностями канала: викторины по постам, "
    "конкурсы и приглашения друзей.\n\n"
    "Команды:\n"
    "/me — мои очки\n"
    "/top — таблица лидеров"
)


@dataclass(frozen=True)
class DeepLink:
    """Разобранный payload: тип и аргумент."""

    kind: str
    value: str


def parse_payload(payload: str | None) -> DeepLink | None:
    """Разобрать payload deep-link. None — ссылка без payload (обычный /start).

    Разделяем по ПЕРВОМУ подчёркиванию: `ref_12345` → ("ref", "12345"),
    `contest_7` → ("contest", "7"), `suggest` → ("suggest", "").
    """
    if not payload:
        return None
    kind, _, value = payload.partition("_")
    if not kind:
        return None
    return DeepLink(kind=kind, value=value)


@router.message(CommandStart())
async def on_start(message: Message, command: CommandObject, bot: Bot) -> None:
    """Приветствие + маршрутизация deep-link."""
    link = parse_payload(command.args)
    user = message.from_user
    user_id = user.id if user is not None else 0

    if link is None:
        await message.answer(_WELCOME)
        return

    if link.kind == PAYLOAD_REFERRAL:
        from engage.handlers.referral import handle_referral_start
        from tg_repost import targets_repo

        targets = [t for t in targets_repo.list_targets() if t.is_active]
        if targets and user_id:
            await handle_referral_start(bot, link.value, user_id, targets[0].chat_id)
    elif link.kind == PAYLOAD_CONTEST:
        from engage.handlers.contest import handle_contest_start

        if user is not None:
            await handle_contest_start(bot, link.value, user, message)
            return  # ответ уже отправлен обработчиком конкурса
    elif link.kind == PAYLOAD_SUGGEST:
        logger.info("Deep-link предложки от %s", user_id)
        await message.answer(f"{_WELCOME}\n\nЧтобы предложить пост: /suggest")
        return
    else:
        # Ссылку могли скопировать из старого поста — молчать нельзя.
        logger.info("Неизвестный deep-link '%s' от %s", link.kind, user_id)

    await message.answer(_WELCOME)
