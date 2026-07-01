"""Данные для дашборда Guardian в веб-админке tg_repost.

Читает БД Guardian напрямую (кросс-пакетный импорт `guardian.*` — см.
docstring `guardian_routes.py` про единую админ-панель на оба бота).
Presentation-only запросы держим рядом с `dashboard.py` репост-бота, не в
самом `guardian/` — у Guardian нет собственного веб-UI, эти данные нужны
только этой странице."""

from __future__ import annotations

from dataclasses import dataclass

from guardian import domains_repo, stopwords_repo, trusted_repo
from guardian.db.models import Member, ModerationLog
from guardian.db.session import session_scope


@dataclass(frozen=True)
class GuardianCounts:
    stopwords: int
    trusted: int
    domains: int
    members: int
    banned: int


def counts(chat_id: int) -> GuardianCounts:
    with session_scope() as session:
        members = session.query(Member).filter(Member.chat_id == chat_id).count()
        banned = (
            session.query(Member)
            .filter(Member.chat_id == chat_id, Member.is_banned.is_(True))
            .count()
        )
    return GuardianCounts(
        stopwords=len(stopwords_repo.list_stopwords()),
        trusted=len(trusted_repo.list_trusted(chat_id)),
        domains=len(domains_repo.list_allowed_domains()),
        members=members,
        banned=banned,
    )


def recent_moderation_log(chat_id: int, limit: int = 15) -> list[ModerationLog]:
    with session_scope() as session:
        return (
            session.query(ModerationLog)
            .filter(ModerationLog.chat_id == chat_id)
            .order_by(ModerationLog.id.desc())
            .limit(limit)
            .all()
        )
