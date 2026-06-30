"""Авто-постинг по расписанию — слоты (F11).

Когда `SCHEDULED_POSTING_ENABLED=true`, одобренные посты не публикуются
мгновенно, а встают в очередь (остаются в статусе `approved`). В заданные
временные слоты (`POSTING_SLOTS`, напр. 10:00,14:00,19:00) выходит до
`POSTING_BATCH_PER_SLOT` постов из очереди — равномерная лента без флуда.
"""

from __future__ import annotations

from telegram.ext import Application

from tg_repost.config import get_settings
from tg_repost.db.models import Post, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger
from tg_repost.telegram.publisher import publish_post

logger = get_logger(__name__)


def parse_slot(slot: str) -> tuple[int, int] | None:
    """Разобрать "HH:MM" в (hour, minute) или вернуть None при ошибке."""
    try:
        hh, mm = slot.split(":", 1)
        hour, minute = int(hh), int(mm)
    except (ValueError, AttributeError):
        return None
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return None


def pending_approved_count() -> int:
    """Сколько одобренных постов ждут публикации в очереди."""
    with session_scope() as session:
        return (
            session.query(Post.id).filter(Post.status == PostStatus.APPROVED).count()
        )


async def publish_slot(application: Application) -> None:
    """Опубликовать порцию одобренных постов (вызывается в каждом слоте)."""
    settings = get_settings()
    batch = max(1, settings.posting_batch_per_slot)

    with session_scope() as session:
        post_ids = [
            row[0]
            for row in session.query(Post.id)
            .filter(Post.status == PostStatus.APPROVED)
            .order_by(Post.created_at.asc())
            .limit(batch)
            .all()
        ]

    if not post_ids:
        logger.info("Слот публикации: очередь пуста")
        return

    logger.info("Слот публикации: публикую %d пост(ов)", len(post_ids))
    for post_id in post_ids:
        try:
            await publish_post(application.bot, post_id)
        except Exception as exc:  # noqa: BLE001
            # Изоляция ошибок: publish_post сам ловит сбои самой отправки
            # (Telegram API), но это страхует от неожиданных исключений ДО
            # них (например, в resolve_targets_for_post) — иначе один плохой
            # пост молча обрывает публикацию остальных постов в этом слоте.
            logger.exception("Слот публикации: пост %s провален: %s", post_id, exc)
