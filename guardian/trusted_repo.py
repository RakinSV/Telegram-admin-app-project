"""CRUD доверенных пользователей (G12) — общий слой для Telegram-команд
(`/trust /untrust`) и веб-админки tg_repost (см. `stopwords_repo.py` про
разделение ответственности). Синхронизирует `Member.is_trusted` и пишет
`ModerationLog` (это часть внутреннего журнала Guardian, не Telegram-
уведомление — тот остаётся на стороне вызывающего, см. `services/log_channel.py`)."""

from __future__ import annotations

from guardian.db.models import Member, ModerationLog, TrustedUser
from guardian.db.session import session_scope


def list_trusted(chat_id: int) -> list[TrustedUser]:
    with session_scope() as session:
        return (
            session.query(TrustedUser)
            .filter(TrustedUser.chat_id == chat_id)
            .order_by(TrustedUser.added_at.desc())
            .all()
        )


def add_trusted(
    user_id: int, chat_id: int, added_by: str, reason: str | None = None
) -> bool:
    """True, если реально добавлен (False — уже был доверенным)."""
    with session_scope() as session:
        exists = (
            session.query(TrustedUser)
            .filter(TrustedUser.user_id == user_id, TrustedUser.chat_id == chat_id)
            .one_or_none()
        )
        if exists is not None:
            return False
        session.add(
            TrustedUser(
                user_id=user_id,
                chat_id=chat_id,
                added_by=added_by,
                reason=reason or None,
            )
        )
        member = (
            session.query(Member)
            .filter(Member.user_id == user_id, Member.chat_id == chat_id)
            .one_or_none()
        )
        if member is not None:
            member.is_trusted = True
        session.add(
            ModerationLog(
                action="trust",
                user_id=user_id,
                chat_id=chat_id,
                reason=reason or None,
                actor=added_by,
            )
        )
        return True


def remove_trusted(user_id: int, chat_id: int, actor: str) -> bool:
    """True, если реально был доверенным (и убран)."""
    with session_scope() as session:
        deleted = (
            session.query(TrustedUser)
            .filter(TrustedUser.user_id == user_id, TrustedUser.chat_id == chat_id)
            .delete()
        )
        if not deleted:
            return False
        member = (
            session.query(Member)
            .filter(Member.user_id == user_id, Member.chat_id == chat_id)
            .one_or_none()
        )
        if member is not None:
            member.is_trusted = False
        session.add(
            ModerationLog(
                action="untrust", user_id=user_id, chat_id=chat_id, actor=actor
            )
        )
        return True
