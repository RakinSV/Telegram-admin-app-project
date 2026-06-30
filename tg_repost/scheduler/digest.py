"""Авто-дайджест недели (F20).

Раз в неделю (по cron-расписанию из main.py) отбирает топ-N опубликованных
постов по просмотрам за период, просит LLM собрать их в один сводный пост и
создаёт Post(kind=DIGEST, status=REWRITTEN) — дальше он идёт по обычному
пайплайну модерации/публикации.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from telegram.ext import Application

from tg_repost.config import get_settings
from tg_repost.db.models import Post, PostKind, PostStat, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger
from tg_repost.rewriter.client import RewriterClient, load_prompt

logger = get_logger(__name__)


def rank_posts_by_views(rows: list[tuple[int, int]], top_n: int) -> list[int]:
    """Отсортировать (post_id, views) по убыванию просмотров, взять top_n
    (чистая функция). При равенстве просмотров — меньший post_id первым
    (стабильный порядок для тестируемости)."""
    ranked = sorted(rows, key=lambda r: (-r[1], r[0]))
    return [post_id for post_id, _ in ranked[:top_n]]


def select_top_posts_for_digest(window_days: int, top_n: int) -> list[Post]:
    """Топ-N опубликованных обычных постов за период по последнему снимку просмотров."""
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    with session_scope() as session:
        posts = (
            session.query(Post)
            .filter(
                Post.kind == PostKind.SOURCE,
                Post.status == PostStatus.POSTED,
                Post.posted_at >= since,
            )
            .all()
        )
        if not posts:
            return []

        rows: list[tuple[int, int]] = []
        for post in posts:
            last = (
                session.query(PostStat)
                .filter(PostStat.post_id == post.id)
                .order_by(PostStat.captured_at.desc())
                .first()
            )
            views = last.view_count if last and last.view_count is not None else 0
            rows.append((post.id, views))

        top_ids = rank_posts_by_views(rows, top_n)
        by_id = {p.id: p for p in posts}
        # Отсоединяем от сессии явные значения, а не ORM-объекты, чтобы не
        # тащить детачнутые инстансы наружу — но Post с expire_on_commit=False
        # безопасен для чтения атрибутов после закрытия сессии (см. db/session.py).
        return [by_id[i] for i in top_ids if i in by_id]


def _format_posts_block(posts: list[Post]) -> str:
    lines = []
    for i, post in enumerate(posts, start=1):
        text = (post.rewritten_text or post.original_text or "").strip()
        snippet = text[:300] + ("…" if len(text) > 300 else "")
        link = f" ({post.source_link})" if post.source_link else ""
        lines.append(f"{i}. {snippet}{link}")
    return "\n".join(lines)


async def build_digest_text(rewriter: RewriterClient, posts: list[Post]) -> str:
    """Собрать текст дайджеста из списка постов через LLM."""
    posts_block = _format_posts_block(posts)
    prompt = load_prompt("digest").format(posts_block=posts_block)
    text = await rewriter.complete(prompt, temperature=0.6)
    return text.strip()


async def run_digest_job(rewriter: RewriterClient, application: Application) -> None:
    """Джоба еженедельного дайджеста (F20). `application` пока не используется
    напрямую — дайджест публикуется через обычный пайплайн модерации/постинга,
    параметр оставлен для единообразия сигнатур job-функций APScheduler."""
    del application  # пайплайн подхватит REWRITTEN-пост на следующем тике
    settings = get_settings()
    posts = select_top_posts_for_digest(settings.digest_window_days, settings.digest_top_n)
    if not posts:
        logger.info("Дайджест: нет опубликованных постов за период — пропуск")
        return

    try:
        text = await build_digest_text(rewriter, posts)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Сборка дайджеста не удалась: %s", exc)
        return

    if not text:
        logger.warning("Дайджест получился пустым — пропуск")
        return

    with session_scope() as session:
        session.add(
            Post(
                kind=PostKind.DIGEST,
                original_text="(дайджест недели)",
                rewritten_text=text,
                status=PostStatus.REWRITTEN,
            )
        )
    logger.info("Дайджест сформирован: %d постов включено", len(posts))
