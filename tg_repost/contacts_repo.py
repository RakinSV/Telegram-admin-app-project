"""Карточка участника — CRM (F63).

Фундамент всей бизнес-обвязки P6: рассылки по сегменту (F64), поддержка
(F68), партнёрская программа (F67) — все они отвечают на вопрос «что это за
человек», и отвечать на него должно одно место.

КАРТОЧКА СОБИРАЕТСЯ ЧТЕНИЕМ, А НЕ ХРАНИТСЯ. Данные о человеке уже лежат в
четырёх местах, и все четыре — источники правды в своих областях:

* `guardian.members` — имя, username, варны, доверие, бан;
* `member_origins` (F41) — откуда пришёл и когда ушёл;
* `referrals` (F42) — кто привёл и скольких привёл сам;
* `user_activity` (F43) — очки, серия, ответы на викторины.

Своя копия этих полей означала бы второй источник правды, который разойдётся
с первым. Хранится только то, чего больше нигде нет: ручные теги и заметка.

ЧТЕНИЕ ДАННЫХ GUARDIAN — ПРЯМОЕ. Так уже работает веб-админка
(`webui/guardian_routes.py`), и это записано там как осознанный выбор.
Механизм синхронизации событиями рассматривался и был отменён: он решал бы
задачу, которой нет (см. решение 2 в `FEATURES.md`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from tg_repost.db.models import ContactNote, ContactTag, MemberOrigin, Referral, UserActivity
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger
from tg_repost.quiz_repo import level_for_points

logger = get_logger(__name__)

MAX_TAG_LEN = 64


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_tag(tag: str) -> str:
    """Тег в канонический вид: без пробелов по краям, в нижнем регистре.

    Без этого «VIP», «vip» и «vip » стали бы тремя разными тегами, и сегмент
    по одному из них молча потерял бы две трети людей.
    """
    return " ".join(tag.strip().lower().split())[:MAX_TAG_LEN]


# --- теги ---


def add_tag(user_id: int, tag: str, *, added_by: str = "manual") -> bool:
    """Повесить тег. `False` — пустой тег или он уже стоит."""
    normalized = normalize_tag(tag)
    if not normalized:
        return False
    with session_scope() as session:
        exists = (
            session.query(ContactTag.id)
            .filter(ContactTag.user_id == user_id, ContactTag.tag == normalized)
            .first()
        )
        if exists:
            return False
        session.add(ContactTag(user_id=user_id, tag=normalized, added_by=added_by))
        return True


def remove_tag(user_id: int, tag: str) -> bool:
    normalized = normalize_tag(tag)
    with session_scope() as session:
        deleted = (
            session.query(ContactTag)
            .filter(ContactTag.user_id == user_id, ContactTag.tag == normalized)
            .delete()
        )
        return bool(deleted)


def tags_of(user_id: int) -> list[str]:
    with session_scope() as session:
        rows = (
            session.query(ContactTag.tag)
            .filter(ContactTag.user_id == user_id)
            .order_by(ContactTag.tag.asc())
            .all()
        )
        return [row[0] for row in rows]


def users_with_tag(tag: str) -> list[int]:
    """id всех, у кого есть тег. Основа сегментов (F64)."""
    normalized = normalize_tag(tag)
    with session_scope() as session:
        rows = (
            session.query(ContactTag.user_id)
            .filter(ContactTag.tag == normalized)
            .order_by(ContactTag.user_id.asc())
            .all()
        )
        return [row[0] for row in rows]


def all_tags() -> list[tuple[str, int]]:
    """Все теги со счётчиком людей, по убыванию популярности."""
    from sqlalchemy import func

    with session_scope() as session:
        rows = (
            session.query(ContactTag.tag, func.count(ContactTag.user_id))
            .group_by(ContactTag.tag)
            .order_by(func.count(ContactTag.user_id).desc(), ContactTag.tag.asc())
            .all()
        )
        return [(tag, count) for tag, count in rows]


# --- заметка ---


def set_note(user_id: int, note: str) -> None:
    """Записать заметку. Пустая строка удаляет её."""
    text = note.strip()
    with session_scope() as session:
        row = (
            session.query(ContactNote).filter(ContactNote.user_id == user_id).first()
        )
        if not text:
            if row is not None:
                session.delete(row)
            return
        if row is None:
            session.add(ContactNote(user_id=user_id, note=text))
        else:
            row.note = text
            row.updated_at = _utcnow()


def note_of(user_id: int) -> str | None:
    with session_scope() as session:
        row = session.query(ContactNote.note).filter(ContactNote.user_id == user_id).first()
        return row[0] if row else None


# --- карточка ---


@dataclass(frozen=True)
class ModerationSummary:
    """Что известно о человеке из Guardian."""

    known: bool
    warn_count: int = 0
    is_trusted: bool = False
    is_banned: bool = False
    is_verified: bool = False


@dataclass(frozen=True)
class ContactCard:
    """Всё, что система знает о человеке, в одном месте."""

    user_id: int
    display_name: str
    username: str | None = None
    first_seen_at: datetime | None = None
    origin: str | None = None
    is_active_member: bool = False
    invited_by: int | None = None
    confirmed_invites: int = 0
    points: int = 0
    level: int = 1
    streak_days: int = 0
    correct_answers: int = 0
    moderation: ModerationSummary = field(
        default_factory=lambda: ModerationSummary(known=False)
    )
    tags: list[str] = field(default_factory=list)
    note: str | None = None


def _moderation_summary(user_id: int) -> ModerationSummary:
    """Данные Guardian. Читаются напрямую — см. docstring модуля.

    Сбой здесь НЕ должен ронять карточку: Guardian — отдельная БД и отдельный
    процесс, его недоступность не повод не показать владельцу всё остальное,
    что мы про человека знаем.
    """
    try:
        from guardian.db.models import Member as GuardianMember
        from guardian.db.session import session_scope as guardian_session

        with guardian_session() as session:
            rows = (
                session.query(GuardianMember)
                .filter(GuardianMember.user_id == user_id)
                .all()
            )
            if not rows:
                return ModerationSummary(known=False)
            # Человек может состоять в нескольких чатах: варны суммируем,
            # а бан и доверие — «хотя бы где-то», потому что владельцу важен
            # сам факт, а не в какой именно группе это случилось.
            return ModerationSummary(
                known=True,
                warn_count=sum(row.warn_count for row in rows),
                is_trusted=any(row.is_trusted for row in rows),
                is_banned=any(row.is_banned for row in rows),
                is_verified=any(row.is_verified for row in rows),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("F63: не удалось прочитать данные Guardian о %s: %s", user_id, exc)
        return ModerationSummary(known=False)


def _identity(user_id: int) -> tuple[str, str | None]:
    """Имя и username. Guardian знает их точнее — он видит каждое сообщение."""
    try:
        from guardian.db.models import Member as GuardianMember
        from guardian.db.session import session_scope as guardian_session

        with guardian_session() as session:
            row = (
                session.query(GuardianMember.username, GuardianMember.first_name)
                .filter(GuardianMember.user_id == user_id)
                .order_by(GuardianMember.id.desc())
                .first()
            )
            if row and (row[0] or row[1]):
                return (row[1] or f"@{row[0]}"), row[0]
    except Exception as exc:  # noqa: BLE001
        logger.debug("F63: имя из Guardian недоступно для %s: %s", user_id, exc)

    with session_scope() as session:
        activity_row = (
            session.query(UserActivity.username)
            .filter(UserActivity.user_id == user_id, UserActivity.username.isnot(None))
            .first()
        )
        if activity_row and activity_row[0]:
            return f"@{activity_row[0]}", activity_row[0]
    return f"id{user_id}", None


def build_card(user_id: int) -> ContactCard:
    """Собрать карточку человека из всех источников."""
    display_name, username = _identity(user_id)

    with session_scope() as session:
        origin_row = (
            session.query(MemberOrigin)
            .filter(MemberOrigin.user_id == user_id)
            # Тай-брейк по `id`: при совпадении меток времени порядок иначе
            # не определён (та же причина, что в `post_stats_repo`).
            .order_by(MemberOrigin.joined_at.desc(), MemberOrigin.id.desc())
            .first()
        )
        referral_row = (
            session.query(Referral.inviter_user_id)
            .filter(Referral.invited_user_id == user_id)
            .first()
        )
        confirmed = (
            session.query(Referral)
            .filter(
                Referral.inviter_user_id == user_id,
                Referral.confirmed_at.isnot(None),
            )
            .count()
        )
        activity_rows = (
            session.query(UserActivity)
            .filter(UserActivity.user_id == user_id)
            .all()
        )

    # Очки суммируются по всем чатам: для владельца это один человек, а не
    # несколько независимых участников.
    points = sum(row.points for row in activity_rows)
    streak = max((row.streak_days for row in activity_rows), default=0)
    correct = sum(row.correct_answers for row in activity_rows)

    return ContactCard(
        user_id=user_id,
        display_name=display_name,
        username=username,
        first_seen_at=origin_row.joined_at if origin_row else None,
        # Имя кампании читаемее сырой ссылки, поэтому оно первое. NULL в
        # обоих полях — человек пришёл не по нашей ссылке (поиск, добавлен
        # админом, ссылка создана вручную в Telegram), и это не «нет данных»,
        # а содержательный ответ «органика».
        origin=(origin_row.invite_name or origin_row.invite_link) if origin_row else None,
        is_active_member=bool(origin_row and origin_row.left_at is None),
        invited_by=referral_row[0] if referral_row else None,
        confirmed_invites=confirmed,
        points=points,
        level=level_for_points(points),
        streak_days=streak,
        correct_answers=correct,
        moderation=_moderation_summary(user_id),
        tags=tags_of(user_id),
        note=note_of(user_id),
    )
