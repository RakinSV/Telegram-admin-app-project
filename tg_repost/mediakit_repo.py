"""Медиакит — карточка канала для рекламодателя (F65).

Самая дешёвая фича блока: НИ ОДНОГО нового сбора данных. Всё уже лежит —
ERR и средние охваты считает F53, динамику подписчиков собирает F22, метрики
постов F14/F31, долю включённых уведомлений F56. Здесь только сборка в один
документ, который не стыдно отправить рекламодателю.

При этом без медиакита рекламу практически не продать: его просят первым же
сообщением, и «сейчас посмотрю в админке и напишу цифры» выглядит ровно так,
как выглядит.

ЧЕСТНОСТЬ ВАЖНЕЕ КРАСИВОЙ ЦИФРЫ. Медиакит — документ для переговоров, в
котором заинтересованная сторона — мы. Поэтому:

* показывается ПОКРЫТИЕ данными: по скольким постам реально есть метрики.
  Средний охват по одному замеренному посту из сорока — это не средний
  охват, и рекламодатель имеет право видеть, из чего цифра посчитана;
* показывается ПЕРИОД. «ERR 32%» без периода не значит ничего;
* отсутствующие данные показываются как отсутствующие, а не как ноль.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from tg_repost import engagement_repo, post_stats_repo
from tg_repost.db.models import ChannelGrowthSnapshot, Post, PostKind, PostStatus, TargetGroup
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

# Сколько лучших постов показываем. Три — достаточно, чтобы дать
# представление о содержании, и мало, чтобы никто не заподозрил витрину.
TOP_POSTS = 3
# Обрезка текста поста в примере: медиакит — не архив канала.
_SNIPPET = 160


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class TopPost:
    post_id: int
    snippet: str
    views: int
    posted_at: datetime | None


@dataclass(frozen=True)
class MediaKit:
    """Всё, что показываем рекламодателю. `None` там, где данных нет."""

    chat_id: int
    channel_title: str
    window_days: int
    generated_at: datetime

    subscribers: int | None = None
    subscribers_delta: int | None = None
    posts_published: int = 0
    posts_with_metrics: int = 0
    avg_views: int | None = None
    reach_rate: float | None = None
    engagement_rate: float | None = None
    notifications_enabled_pct: float | None = None
    top_posts: tuple[TopPost, ...] = ()

    @property
    def has_enough_data(self) -> bool:
        """Хватает ли данных, чтобы документ вообще что-то значил.

        Медиакит без охватов — это лист бумаги с названием канала. Лучше
        честно сказать «данных пока мало», чем отдать рекламодателю пустоту
        и получить вопрос, на который нечего ответить.
        """
        return self.avg_views is not None and self.posts_with_metrics > 0

    @property
    def coverage_note_needed(self) -> bool:
        """Нужна ли оговорка про неполное покрытие метриками."""
        return (
            self.posts_with_metrics > 0
            and self.posts_with_metrics < self.posts_published
        )


def _subscribers(chat_id: int, window_days: int) -> tuple[int | None, int | None]:
    """Текущее число подписчиков и прирост за период (F22)."""
    since = _utcnow() - timedelta(days=window_days)
    with session_scope() as session:
        rows = (
            session.query(ChannelGrowthSnapshot.subscriber_count)
            .filter(
                ChannelGrowthSnapshot.chat_id == chat_id,
                ChannelGrowthSnapshot.captured_at >= since,
            )
            # Тай-брейк по `id` — при совпадении меток времени порядок иначе
            # не определён (та же причина, что во всей работе с метриками).
            .order_by(
                ChannelGrowthSnapshot.captured_at.asc(),
                ChannelGrowthSnapshot.id.asc(),
            )
            .all()
        )
    if not rows:
        return None, None
    first, last = rows[0][0], rows[-1][0]
    # Прирост показываем только когда есть хотя бы два замера: разница
    # значения с самим собой — это не «нулевой рост», а «мы не знаем».
    delta = (last - first) if len(rows) >= 2 else None
    return last, delta


def _top_posts(chat_id: int, window_days: int) -> tuple[TopPost, ...]:
    """Лучшие посты периода по просмотрам."""
    since = _utcnow() - timedelta(days=window_days)
    with session_scope() as session:
        posts = (
            session.query(Post)
            .filter(
                Post.kind == PostKind.SOURCE,
                Post.status == PostStatus.POSTED,
                Post.posted_chat_id == chat_id,
                Post.posted_at >= since,
            )
            .all()
        )
        if not posts:
            return ()
        views_by_post = post_stats_repo.latest_views_for(
            session, [post.id for post in posts]
        )
        ranked = sorted(
            posts,
            key=lambda post: (-views_by_post.get(post.id, 0), post.id),
        )
        out: list[TopPost] = []
        for post in ranked[:TOP_POSTS]:
            views = views_by_post.get(post.id, 0)
            if not views:
                # Пост без замеров не может быть «лучшим»: мы про него просто
                # ничего не знаем, и показывать его в витрине нечестно.
                continue
            text = (post.rewritten_text or post.original_text or "").strip()
            out.append(
                TopPost(
                    post_id=post.id,
                    snippet=" ".join(text.split())[:_SNIPPET],
                    views=views,
                    posted_at=post.posted_at,
                )
            )
        return tuple(out)


def _notifications_pct(chat_id: int) -> float | None:
    """Доля подписчиков с включёнными уведомлениями (F56), если собрана."""
    from tg_repost.db.models import ChannelStatsSnapshot

    with session_scope() as session:
        row = (
            session.query(ChannelStatsSnapshot.notifications_enabled_pct)
            .filter(
                ChannelStatsSnapshot.chat_id == chat_id,
                ChannelStatsSnapshot.notifications_enabled_pct.isnot(None),
            )
            .order_by(
                ChannelStatsSnapshot.captured_at.desc(),
                ChannelStatsSnapshot.id.desc(),
            )
            .first()
        )
        return row[0] if row else None


def build(chat_id: int, window_days: int = 30) -> MediaKit | None:
    """Собрать медиакит канала. `None` — такого канала нет в целях."""
    with session_scope() as session:
        target = (
            session.query(TargetGroup)
            .filter(TargetGroup.chat_id == chat_id)
            .first()
        )
        if target is None:
            return None
        title = target.title or str(chat_id)

    subscribers, delta = _subscribers(chat_id, window_days)
    engagement = engagement_repo.build_engagement_report(chat_id, window_days)

    return MediaKit(
        chat_id=chat_id,
        channel_title=title,
        window_days=window_days,
        generated_at=_utcnow(),
        subscribers=subscribers,
        subscribers_delta=delta,
        posts_published=engagement.posts_total,
        posts_with_metrics=engagement.posts_with_stats,
        avg_views=engagement.avg_views,
        reach_rate=engagement.reach_rate,
        engagement_rate=engagement.engagement_rate,
        notifications_enabled_pct=_notifications_pct(chat_id),
        top_posts=_top_posts(chat_id, window_days),
    )
