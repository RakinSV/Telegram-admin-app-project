"""Вставка нативной рекламы в ленту (F21).

Каждый N-й опубликованный обычный пост — рекламный (`AD_EVERY_NTH_POST`).
Рекламный Post создаётся сразу со статусом `rewritten` (текст уже сгенерирован
из брифа через LLM) и дальше идёт по тому же пайплайну модерации/публикации,
что и обычные посты — без отдельной логики в jobs/moderation_bot/publisher.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from tg_repost.config import get_settings
from tg_repost.db.models import AdBrief, Post, PostKind, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger
from tg_repost.rewriter.client import RewriterClient, load_prompt

logger = get_logger(__name__)


def ads_due(posted_normal_count: int, existing_ad_count: int, every_nth: int) -> bool:
    """Должен ли сейчас появиться очередной рекламный пост (чистая функция).

    Реклама нужна каждые `every_nth` опубликованных обычных постов. Сравнение
    идёт по количеству уже СОЗДАННЫХ рекламных постов (не только опубликованных)
    — это не даёт создать вторую рекламу, пока первая ещё не вышла.
    """
    if every_nth <= 0:
        return False
    return (posted_normal_count // every_nth) > existing_ad_count


def select_next_ad_brief(session: Session) -> AdBrief | None:
    """Выбрать следующий активный бриф по принципу round-robin (меньше всего
    использованный, при равенстве — самый старый)."""
    return (
        session.query(AdBrief)
        .filter(
            AdBrief.is_active.is_(True),
            (AdBrief.max_uses.is_(None)) | (AdBrief.times_used < AdBrief.max_uses),
        )
        .order_by(AdBrief.times_used.asc(), AdBrief.id.asc())
        .first()
    )


async def inject_native_ad(rewriter: RewriterClient) -> None:
    """Создать рекламный пост, если он сейчас due и есть активный бриф."""
    settings = get_settings()

    with session_scope() as session:
        posted_normal = (
            session.query(Post.id)
            .filter(Post.kind == PostKind.SOURCE, Post.status == PostStatus.POSTED)
            .count()
        )
        existing_ads = session.query(Post.id).filter(Post.kind == PostKind.AD).count()

    if not ads_due(posted_normal, existing_ads, settings.ad_every_nth_post):
        return

    with session_scope() as session:
        brief = select_next_ad_brief(session)
        if brief is None:
            logger.debug("Реклама due, но нет активных брифов")
            return
        brief_id = brief.id
        brief_text = brief.brief_text

    try:
        text = await rewriter.complete(load_prompt("native_ad").format(brief_text=brief_text))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Генерация рекламного поста провалена (бриф #%s): %s", brief_id, exc)
        return

    text = text.strip()
    if not text:
        logger.warning("Рекламный пост (бриф #%s) получился пустым — пропуск", brief_id)
        return

    with session_scope() as session:
        session.add(
            Post(
                kind=PostKind.AD,
                ad_brief_id=brief_id,
                original_text=brief_text,
                rewritten_text=text,
                status=PostStatus.REWRITTEN,
            )
        )
        brief_row = session.get(AdBrief, brief_id)
        if brief_row is not None:
            brief_row.times_used += 1
            if brief_row.max_uses is not None and brief_row.times_used >= brief_row.max_uses:
                brief_row.is_active = False

    logger.info("Рекламный пост создан (бриф #%s)", brief_id)
