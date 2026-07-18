"""Bot API обвязка для инвайт-ссылок и заявок на вступление (F32) — тонкий
слой над `python-telegram-bot`, бизнес-логика/хранение в `invites_repo.py`."""

from __future__ import annotations

from telegram import Bot

from tg_repost import invites_repo
from tg_repost.db.models import InviteLink
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)


async def create_invite_link(
    bot: Bot,
    chat_id: int,
    name: str | None = None,
    member_limit: int | None = None,
    creates_join_request: bool = False,
) -> InviteLink:
    """Создать новую инвайт-ссылку в чате и сохранить её (Bot API не даёт
    способа перечислить уже существующие ссылки — см. `InviteLink` docstring)."""
    link = await bot.create_chat_invite_link(
        chat_id=chat_id,
        name=name or None,
        member_limit=member_limit,
        creates_join_request=creates_join_request,
    )
    return invites_repo.record_invite_link(
        chat_id, link.invite_link, name or None, member_limit, creates_join_request,
    )


async def revoke_invite_link(bot: Bot, link_id: int) -> bool:
    """Отозвать ссылку. False, если запись не найдена."""
    link = invites_repo.get_invite_link(link_id)
    if link is None:
        return False
    await bot.revoke_chat_invite_link(chat_id=link.chat_id, invite_link=link.invite_link)
    invites_repo.mark_revoked(link_id)
    return True


async def approve_join_request(bot: Bot, request_id: int) -> bool:
    """Одобрить заявку на вступление. False, если заявка не найдена/уже решена."""
    request = invites_repo.get_join_request(request_id)
    if request is None or request.status != "pending":
        return False
    await bot.approve_chat_join_request(chat_id=request.chat_id, user_id=request.user_id)
    invites_repo.decide_join_request(request_id, approved=True)
    return True


async def decline_join_request(bot: Bot, request_id: int) -> bool:
    """Отклонить заявку на вступление. False, если заявка не найдена/уже решена."""
    request = invites_repo.get_join_request(request_id)
    if request is None or request.status != "pending":
        return False
    await bot.decline_chat_join_request(chat_id=request.chat_id, user_id=request.user_id)
    invites_repo.decide_join_request(request_id, approved=False)
    return True
