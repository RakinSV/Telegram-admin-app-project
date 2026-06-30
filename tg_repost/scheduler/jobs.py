"""Джобы пайплайна (F06 рерайт, оркестрация модерации).

Один периодический тик:
  1. Берёт посты `new` → рерайтит → `rewritten` (F06).
  2. Отправляет `rewritten` владельцу на модерацию (F07),
     либо при AUTO_POST_ENABLED — сразу одобряет и публикует (F11, Фаза 2).
"""

from __future__ import annotations

from telegram.ext import Application

from tg_repost.ads.injector import inject_native_ad
from tg_repost.config import get_settings
from tg_repost.covers.dispatcher import generate_cover
from tg_repost.db.models import Post, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.enrichment.enricher import enrich_post, enrichment_enabled_for
from tg_repost.logging_conf import get_logger
from tg_repost.rewriter.client import RewriterClient, resolve_style_prompt
from tg_repost.telegram.moderation_bot import send_pending_for_approval
from tg_repost.telegram.publisher import publish_post

logger = get_logger(__name__)


async def rewrite_new_posts(rewriter: RewriterClient, batch: int = 5) -> None:
    """Рерайтнуть посты со статусом `new` (F06)."""
    with session_scope() as session:
        post_ids = [
            row[0]
            for row in session.query(Post.id)
            .filter(Post.status == PostStatus.NEW)
            .order_by(Post.created_at.asc())
            .limit(batch)
            .all()
        ]

    for post_id in post_ids:
        # Резервируем пост: new → rewriting. Заодно читаем стиль источника (F15)
        # и решаем, нужно ли обогащение (F16).
        with session_scope() as session:
            post = session.get(Post, post_id)
            if post is None or post.status != PostStatus.NEW:
                continue
            post.set_status(PostStatus.REWRITING)
            original = post.original_text
            style = post.source.style_profile if post.source else None
            enrich = enrichment_enabled_for(post.source)
            has_media = bool(post.media_path)

        prompt_name = resolve_style_prompt(style)
        try:
            result = await rewriter.rewrite(original, prompt_name=prompt_name)
        except Exception as exc:  # noqa: BLE001
            logger.error("Рерайт поста %s провален: %s", post_id, exc)
            with session_scope() as session:
                post = session.get(Post, post_id)
                if post:
                    post.set_status(PostStatus.FAILED, reason=f"ошибка рерайта: {exc}")
            continue

        final_text = result.text
        # F16 — добор источников (не критично: при ошибке просто без блока).
        if enrich:
            block = await enrich_post(rewriter, original)
            if block:
                final_text = f"{final_text}\n{block}"

        # F18 — авто-обложка, только если у поста ещё нет своего медиа.
        cover_path: str | None = None
        if not has_media:
            cover_path = await generate_cover(rewriter, original)

        with session_scope() as session:
            post = session.get(Post, post_id)
            if post:
                post.rewritten_text = final_text
                post.rewrite_tokens = result.total_tokens
                if cover_path:
                    post.media_path = cover_path
                post.set_status(PostStatus.REWRITTEN)
        logger.info(
            "Пост %s рерайчен (стиль=%s, обогащение=%s, обложка=%s, %d токенов)",
            post_id, prompt_name, enrich, bool(cover_path), result.total_tokens,
        )


async def _auto_publish_rewritten(application: Application) -> None:
    """Режим без модерации: rewritten → approved (→ posted, если без слотов).

    Если включено расписание по слотам (F11), посты остаются `approved` в
    очереди — публикация произойдёт в слот (см. scheduler/posting.py).
    """
    settings = get_settings()
    with session_scope() as session:
        post_ids = [
            row[0]
            for row in session.query(Post.id)
            .filter(Post.status == PostStatus.REWRITTEN)
            .order_by(Post.created_at.asc())
            .limit(10)
            .all()
        ]
    for post_id in post_ids:
        with session_scope() as session:
            post = session.get(Post, post_id)
            if post is None or post.status != PostStatus.REWRITTEN:
                continue
            post.set_status(PostStatus.APPROVED)
        if not settings.scheduled_posting_enabled:
            await publish_post(application.bot, post_id)


async def pipeline_tick(rewriter: RewriterClient, application: Application) -> None:
    """Один проход пайплайна: рерайт + реклама (F21) + (модерация | авто-постинг)."""
    settings = get_settings()
    try:
        await rewrite_new_posts(rewriter)
        await inject_native_ad(rewriter)
        if settings.auto_post_enabled:
            await _auto_publish_rewritten(application)
        else:
            await send_pending_for_approval(application)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ошибка в pipeline_tick: %s", exc)
