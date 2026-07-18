"""`my_chat_member` (F28.10) — обнаружение, реально ли Guardian может
модерировать чат (админка + право ограничивать участников), а не просто
факт "галочка use_guardian стоит". Владелец мог отметить цель, но забыть
выдать самому боту Guardian права администратора — без этого варны/муты/
антирейд (G05/G06/G14) молча проваливаются на `TelegramBadRequest`.

Симметрично `tg_repost/telegram/moderation_bot.py::_on_my_chat_member`
(та же идея для прав ПОСТИТЬ у репост-бота), но результат пишется НАПРЯМУЮ
в БД tg_repost (`TargetGroup.guardian_can_moderate`) — кросс-пакетный
импорт из процесса Guardian, тот же приём, каким `webui/guardian_routes.py`
читает/пишет БД Guardian из процесса tg_repost в обратную сторону."""

from __future__ import annotations

from aiogram import Router
from aiogram.enums import ChatMemberStatus
from aiogram.types import ChatMemberUpdated

from guardian.logging_conf import get_logger
from tg_repost import targets_repo

logger = get_logger(__name__)
router = Router(name="chat_member")


def _can_moderate(member: object) -> bool:
    """Владелец чата — всегда может всё. Админ — только если явно выдано
    право ограничивать участников (мут/кик/бан — весь смысл Guardian).
    Любой другой статус (member/restricted/left/kicked) — не может."""
    status = getattr(member, "status", None)
    if status == ChatMemberStatus.CREATOR:
        return True
    if status != ChatMemberStatus.ADMINISTRATOR:
        return False
    return bool(getattr(member, "can_restrict_members", False))


@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated) -> None:
    """F28.10: сработает при любой смене статуса САМОГО Guardian-бота —
    добавили админом, сняли админку, выгнали из чата и т.п."""
    chat_id = event.chat.id
    can_moderate = _can_moderate(event.new_chat_member)
    updated = targets_repo.sync_guardian_can_moderate(chat_id, can_moderate)
    if updated and not can_moderate:
        logger.warning(
            "Guardian не может модерировать чат %s (статус: %s) — выдай "
            "боту права администратора с разрешением ограничивать участников",
            chat_id,
            getattr(event.new_chat_member, "status", "unknown"),
        )
