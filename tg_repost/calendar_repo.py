"""Контент-календарь (F72) — что выходило и что запланировано.

ЧЕСТНОСТЬ ГОРИЗОНТА. Посты в этой системе НЕ привязаны к датам по умолчанию:
они копятся одобренными и уходят пачкой в ближайший слот расписания (F11).
Поэтому нарисовать «пост X выйдет в пятницу» нельзя — такой информации
просто нет, и придумывать её значило бы показывать владельцу расписание,
которого система не исполняет.

Что календарь показывает на самом деле:

* **прошлое — факты**: что и когда вышло (`posted_at`);
* **будущее — обязательства**: посты с явной датой «не раньше»
  (`scheduled_for`, F72) и забронированные рекламные места (F66);
* **очередь** — сколько постов ждут публикации без даты. Они выйдут «когда
  дойдёт очередь», и это честнее, чем размазать их по дням наугад.

Реклама и обычные посты — на ОДНОЙ сетке намеренно: владелец планирует одну
ленту, а не две. Разнеси их — и рекламный пост встанет в день, где уже стоит
анонс, потому что при планировании его не было видно.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from tg_repost import ad_requests_repo
from tg_repost.db.models import Post, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

# Насколько назад и вперёд рисуем сетку.
PAST_DAYS = 7
FUTURE_DAYS = 21

_SNIPPET = 80


@dataclass(frozen=True)
class CalendarPost:
    post_id: int
    snippet: str
    kind: str
    is_published: bool
    needs_owner_approval: bool = False


@dataclass
class CalendarDay:
    day: date
    is_past: bool
    is_today: bool
    posts: list[CalendarPost] = field(default_factory=list)
    ad_advertiser: str | None = None


@dataclass(frozen=True)
class CalendarView:
    days: list[CalendarDay]
    # Посты без даты: выйдут «когда дойдёт очередь». Показываются числом, а
    # не разложенными по дням — иначе календарь врал бы о том, чего не знает.
    undated_queue: int
    awaiting_owner: int


def _snippet(post: Post) -> str:
    text = (post.rewritten_text or post.original_text or "").strip()
    return " ".join(text.split())[:_SNIPPET]


def build(chat_id: int | None = None) -> CalendarView:
    """Собрать сетку: факты прошлого и обязательства будущего."""
    today = datetime.now(timezone.utc).date()
    first = today - timedelta(days=PAST_DAYS)
    last = today + timedelta(days=FUTURE_DAYS)

    days = {
        first + timedelta(days=i): CalendarDay(
            day=first + timedelta(days=i),
            is_past=(first + timedelta(days=i)) < today,
            is_today=(first + timedelta(days=i)) == today,
        )
        for i in range((last - first).days + 1)
    }

    with session_scope() as session:
        published = session.query(Post).filter(
            Post.status == PostStatus.POSTED,
            Post.posted_at.isnot(None),
        )
        if chat_id is not None:
            published = published.filter(Post.posted_chat_id == chat_id)
        for post in published.all():
            if post.posted_at is None:
                continue  # отфильтровано запросом, но типам это неизвестно
            day = post.posted_at.date()
            if day in days:
                days[day].posts.append(
                    CalendarPost(
                        post_id=post.id, snippet=_snippet(post),
                        kind=post.kind.value if post.kind else "source",
                        is_published=True,
                    )
                )

        scheduled = (
            session.query(Post)
            .filter(
                Post.status.in_([PostStatus.APPROVED, PostStatus.PENDING_APPROVAL]),
                Post.scheduled_for.isnot(None),
            )
            .all()
        )
        for post in scheduled:
            if post.scheduled_for in days:
                days[post.scheduled_for].posts.append(
                    CalendarPost(
                        post_id=post.id, snippet=_snippet(post),
                        kind=post.kind.value if post.kind else "source",
                        is_published=False,
                        needs_owner_approval=post.needs_owner_approval,
                    )
                )

        undated = (
            session.query(Post)
            .filter(
                Post.status == PostStatus.APPROVED,
                Post.scheduled_for.is_(None),
                Post.needs_owner_approval.is_(False),
            )
            .count()
        )
        awaiting = (
            session.query(Post)
            .filter(Post.needs_owner_approval.is_(True))
            .count()
        )

    # Рекламные брони — на ту же сетку: владелец планирует одну ленту.
    if chat_id is not None:
        for slot_date, request in ad_requests_repo.occupied_dates(chat_id).items():
            if slot_date in days:
                days[slot_date].ad_advertiser = request.advertiser

    return CalendarView(
        days=[days[key] for key in sorted(days)],
        undated_queue=undated,
        awaiting_owner=awaiting,
    )


def schedule_post(post_id: int, day: date | None) -> bool:
    """Поставить пост на дату «не раньше». `None` — снять ограничение."""
    with session_scope() as session:
        post = session.get(Post, post_id)
        if post is None or post.status in (PostStatus.POSTED, PostStatus.REJECTED):
            # Опубликованное уже вышло, отклонённое не выйдет — двигать в
            # календаре нечего, и молча делать вид, что получилось, нельзя.
            return False
        post.scheduled_for = day
        return True


def approve_by_owner(post_id: int) -> bool:
    """Снять требование подтверждения владельцем."""
    with session_scope() as session:
        post = session.get(Post, post_id)
        if post is None or not post.needs_owner_approval:
            return False
        post.needs_owner_approval = False
        return True


def mark_approved(post_id: int, *, by_username: str, by_role: str) -> None:
    """Записать, кто одобрил, и решить, нужен ли владелец.

    Требование второго подтверждения включается настройкой и по умолчанию
    ВЫКЛЮЧЕНО: навязывать согласование там, где владелец работает один или
    полностью доверяет редактору, — это церемония, которая только замедляет.
    """
    from tg_repost.config import get_settings
    from tg_repost.webui.access import ROLE_OWNER

    settings = get_settings()
    with session_scope() as session:
        post = session.get(Post, post_id)
        if post is None:
            return
        post.approved_by = by_username
        post.needs_owner_approval = bool(
            settings.require_owner_approval and by_role != ROLE_OWNER
        )
        if post.needs_owner_approval:
            logger.info(
                "F72: пост #%d одобрен редактором %s и ждёт владельца",
                post_id, by_username,
            )


def posts_awaiting_owner() -> list[CalendarPost]:
    with session_scope() as session:
        rows = (
            session.query(Post)
            .filter(Post.needs_owner_approval.is_(True))
            .order_by(Post.created_at.asc())
            .all()
        )
        return [
            CalendarPost(
                post_id=row.id, snippet=_snippet(row),
                kind=row.kind.value if row.kind else "source",
                is_published=False, needs_owner_approval=True,
            )
            for row in rows
        ]
