"""Семантический дубль-чек через эмбеддинги (F13).

Вектор эмбеддинга упаковывается в BLOB (`array('f')`) и хранится в
`posts.embedding`. Дубль определяется по косинусному сходству с постами за
последние N дней. Без внешних зависимостей (numpy не требуется на этом масштабе).
"""

from __future__ import annotations

import math
from array import array
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from tg_repost.db.models import Post, PostStatus


def pack_embedding(vector: list[float]) -> bytes:
    """Упаковать список float в BLOB (float32)."""
    return array("f", vector).tobytes()


def unpack_embedding(blob: bytes) -> list[float]:
    """Распаковать BLOB обратно в список float."""
    arr = array("f")
    arr.frombytes(blob)
    return list(arr)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Косинусное сходство двух векторов одинаковой длины."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def find_similar_post(
    session: Session,
    embedding: list[float],
    *,
    threshold: float,
    window_days: int,
) -> tuple[int, float] | None:
    """Найти недавний пост с косинусным сходством >= threshold.

    Возвращает (post_id, similarity) самого похожего поста выше порога либо None.
    Сравнение идёт с постами, у которых есть эмбеддинг и которые не помечены
    дублем/отфильтрованными.
    """
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    candidates = (
        session.query(Post.id, Post.embedding)
        .filter(
            Post.embedding.is_not(None),
            Post.created_at >= since,
            Post.status.notin_([PostStatus.DUPLICATE, PostStatus.FILTERED_OUT]),
        )
        .all()
    )

    best_id: int | None = None
    best_sim = 0.0
    for post_id, blob in candidates:
        if not blob:
            continue
        sim = cosine_similarity(embedding, unpack_embedding(blob))
        if sim >= threshold and sim > best_sim:
            best_sim = sim
            best_id = post_id

    if best_id is None:
        return None
    return best_id, best_sim
