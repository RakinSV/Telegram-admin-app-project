"""CRUD/выбор вариантов рерайта и обложки поста (F06/F18-доп.) —
настраиваемое число вариантов, генерируемых на каждый пост (см.
`scheduler/jobs.py::rewrite_new_posts`). Активный вариант денормализован на
`Post.rewritten_text`/`media_path` (см. комментарий у этих полей в
`db/models.py`) — так `moderation.py`/`publish_post`/дашборд/статистика
продолжают читать один-единственный текст/картинку, не зная о вариантах.

Переиспользуется и ботом (`telegram/moderation_bot.py`, кнопки ◀▶), и
веб-админкой (`webui/crud_routes.py`, роуты `/moderation/{id}/select-*`).
"""

from __future__ import annotations

from tg_repost.db.models import Post, PostCoverVariant, PostRewriteVariant
from tg_repost.db.session import session_scope


def list_rewrite_variants(post_id: int) -> list[PostRewriteVariant]:
    with session_scope() as session:
        return (
            session.query(PostRewriteVariant)
            .filter(PostRewriteVariant.post_id == post_id)
            .order_by(PostRewriteVariant.variant_index)
            .all()
        )


def list_cover_variants(post_id: int) -> list[PostCoverVariant]:
    with session_scope() as session:
        return (
            session.query(PostCoverVariant)
            .filter(PostCoverVariant.post_id == post_id)
            .order_by(PostCoverVariant.variant_index)
            .all()
        )


def active_rewrite_language(post_id: int) -> str | None:
    """Язык активного варианта текста — для подписи кнопки ◀▶ при модерации.

    None, если вариантов нет вовсе (пост-реклама, дайджест, опрос — у них
    нет рерайта): тогда подпись остаётся прежней, без языка.
    """
    with session_scope() as session:
        post = session.get(Post, post_id)
        if post is None:
            return None
        variant = (
            session.query(PostRewriteVariant)
            .filter(
                PostRewriteVariant.post_id == post_id,
                PostRewriteVariant.variant_index == (post.active_rewrite_variant_index or 0),
            )
            .one_or_none()
        )
        return variant.language if variant else None


def select_rewrite_variant(post_id: int, variant_index: int) -> bool:
    """Сделать вариант текста активным (копирует в `Post.rewritten_text`).

    False, если пост или вариант с таким индексом не найден.
    """
    with session_scope() as session:
        post = session.get(Post, post_id)
        if post is None:
            return False
        variant = (
            session.query(PostRewriteVariant)
            .filter(
                PostRewriteVariant.post_id == post_id,
                PostRewriteVariant.variant_index == variant_index,
            )
            .one_or_none()
        )
        if variant is None:
            return False
        post.rewritten_text = variant.text
        post.active_rewrite_variant_index = variant_index
        return True


def select_cover_variant(post_id: int, variant_index: int) -> bool:
    """Сделать вариант обложки активным (копирует в `Post.media_path`).

    False, если пост или вариант с таким индексом не найден.
    """
    with session_scope() as session:
        post = session.get(Post, post_id)
        if post is None:
            return False
        variant = (
            session.query(PostCoverVariant)
            .filter(
                PostCoverVariant.post_id == post_id,
                PostCoverVariant.variant_index == variant_index,
            )
            .one_or_none()
        )
        if variant is None:
            return False
        post.media_path = variant.media_path
        post.active_cover_variant_index = variant_index
        return True
