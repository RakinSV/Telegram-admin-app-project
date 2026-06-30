"""Сбор статистики опубликованных постов (F14).

Периодически опрашивает просмотры/пересылки/реакции опубликованных постов
через Telethon (юзер-сессия видит метрики каналов) и пишет снимки в
`post_stats`. Команда бота `/stats` и веб-страница `/stats` (Фаза 5.3)
агрегируют данные за период через `compute_stats_summary` — структурированные
данные отдельно от текстового форматирования, как и в `smart_schedule.py`/
`growth.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient

from tg_repost.antiban import jitter_sleep
from tg_repost.config import get_settings
from tg_repost.db.models import Post, PostStat, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)


def _count_reactions(message) -> int | None:
    """Суммарное число реакций на сообщении Telethon (если есть)."""
    reactions = getattr(message, "reactions", None)
    if not reactions or not getattr(reactions, "results", None):
        return None
    return sum(getattr(r, "count", 0) for r in reactions.results)


async def collect_stats(client: TelegramClient) -> int:
    """Снять метрики недавно опубликованных постов. Возвращает число снимков."""
    settings = get_settings()
    since = datetime.now(timezone.utc) - timedelta(days=settings.stats_window_days)

    with session_scope() as session:
        targets = [
            (p.id, p.posted_chat_id, p.posted_message_id)
            for p in session.query(Post)
            .filter(
                Post.status == PostStatus.POSTED,
                Post.posted_message_id.is_not(None),
                Post.posted_chat_id.is_not(None),
                Post.posted_at >= since,
            )
            .all()
        ]

    captured = 0
    for post_id, chat_id, message_id in targets:
        try:
            message = await client.get_messages(chat_id, ids=message_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось получить метрики поста %s: %s", post_id, exc)
            continue
        if message is None:
            continue

        with session_scope() as session:
            session.add(
                PostStat(
                    post_id=post_id,
                    view_count=getattr(message, "views", None),
                    forward_count=getattr(message, "forwards", None),
                    reaction_count=_count_reactions(message),
                )
            )
        captured += 1
        # F17 — мягкий джиттер между запросами метрик.
        await jitter_sleep(0.3, 1.0)

    logger.info("Статистика собрана по %d постам", captured)
    return captured


@dataclass(frozen=True)
class StatsSummary:
    """Структурированная сводка статистики за период (для /stats и веб-страницы)."""

    window_days: int
    published: int
    counted: int
    total_views: int
    avg_views: float
    top_post_id: int | None
    top_post_views: int


def compute_stats_summary(window_days: int) -> StatsSummary:
    """Сводка по опубликованным постам за период (последний снимок на пост)."""
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    with session_scope() as session:
        posts = (
            session.query(Post)
            .filter(Post.status == PostStatus.POSTED, Post.posted_at >= since)
            .all()
        )
        if not posts:
            return StatsSummary(
                window_days=window_days, published=0, counted=0, total_views=0,
                avg_views=0.0, top_post_id=None, top_post_views=0,
            )

        total_views = 0
        counted = 0
        best: tuple[int, int | None] = (0, None)  # (views, post_id)
        for post in posts:
            last = (
                session.query(PostStat)
                .filter(PostStat.post_id == post.id)
                .order_by(PostStat.captured_at.desc())
                .first()
            )
            if last and last.view_count is not None:
                total_views += last.view_count
                counted += 1
                if last.view_count > best[0]:
                    best = (last.view_count, post.id)

        published = len(posts)
        avg = total_views / counted if counted else 0.0

    return StatsSummary(
        window_days=window_days, published=published, counted=counted,
        total_views=total_views, avg_views=avg,
        top_post_id=best[1], top_post_views=best[0],
    )


def stats_summary(window_days: int) -> str:
    """Текстовая сводка для команды бота /stats."""
    summary = compute_stats_summary(window_days)
    if summary.published == 0:
        return f"За последние {window_days} дн. опубликованных постов нет."

    lines = [
        f"📊 Статистика за {window_days} дн.:",
        f"• Опубликовано постов: {summary.published}",
        f"• С метриками просмотров: {summary.counted}",
        f"• Суммарно просмотров: {summary.total_views}",
        f"• В среднем на пост: {summary.avg_views:.0f}",
    ]
    if summary.top_post_id is not None:
        lines.append(f"• Топ-пост: #{summary.top_post_id} ({summary.top_post_views} просмотров)")
    return "\n".join(lines)
