"""CRUD-доступ к инвайт-ссылкам и заявкам на вступление (F32) — используется
`telegram/invites.py` (Bot API вызовы) и веб-админкой/ботом (одобрение/
отклонение, показ списков)."""

from __future__ import annotations

from datetime import datetime, timezone

from tg_repost.db.models import InviteLink, JoinRequestRecord
from tg_repost.db.session import session_scope


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- Инвайт-ссылки ---


def record_invite_link(
    chat_id: int,
    invite_link: str,
    name: str | None,
    member_limit: int | None,
    creates_join_request: bool,
) -> InviteLink:
    with session_scope() as session:
        link = InviteLink(
            chat_id=chat_id, invite_link=invite_link, name=name,
            member_limit=member_limit, creates_join_request=creates_join_request,
        )
        session.add(link)
        session.flush()
        session.refresh(link)
        return link


def list_invite_links(chat_id: int | None = None) -> list[InviteLink]:
    with session_scope() as session:
        query = session.query(InviteLink)
        if chat_id is not None:
            query = query.filter(InviteLink.chat_id == chat_id)
        return query.order_by(InviteLink.id.desc()).all()


def get_invite_link(link_id: int) -> InviteLink | None:
    with session_scope() as session:
        return session.get(InviteLink, link_id)


def mark_revoked(link_id: int) -> bool:
    with session_scope() as session:
        link = session.get(InviteLink, link_id)
        if link is None:
            return False
        link.is_revoked = True
        return True


# --- Заявки на вступление ---


def record_join_request(chat_id: int, user_id: int, username: str | None, bio: str | None) -> None:
    """Апсерт: если у этого пользователя уже есть PENDING заявка в этот
    чат — обновляем bio/время (Telegram может прислать `chat_join_request`
    снова, если пользователь отменил и переотправил заявку до решения),
    иначе создаём новую строку."""
    with session_scope() as session:
        existing = (
            session.query(JoinRequestRecord)
            .filter(
                JoinRequestRecord.chat_id == chat_id,
                JoinRequestRecord.user_id == user_id,
                JoinRequestRecord.status == "pending",
            )
            .one_or_none()
        )
        if existing is not None:
            existing.username = username
            existing.bio = bio
            existing.requested_at = _utcnow()
            return
        session.add(
            JoinRequestRecord(
                chat_id=chat_id, user_id=user_id, username=username, bio=bio,
            )
        )


def list_pending_join_requests(chat_id: int | None = None) -> list[JoinRequestRecord]:
    with session_scope() as session:
        query = session.query(JoinRequestRecord).filter(JoinRequestRecord.status == "pending")
        if chat_id is not None:
            query = query.filter(JoinRequestRecord.chat_id == chat_id)
        return query.order_by(JoinRequestRecord.requested_at).all()


def get_join_request(request_id: int) -> JoinRequestRecord | None:
    with session_scope() as session:
        return session.get(JoinRequestRecord, request_id)


def decide_join_request(request_id: int, approved: bool) -> JoinRequestRecord | None:
    with session_scope() as session:
        request = session.get(JoinRequestRecord, request_id)
        if request is None or request.status != "pending":
            return None
        request.status = "approved" if approved else "declined"
        request.decided_at = _utcnow()
        session.flush()
        session.refresh(request)
        return request
