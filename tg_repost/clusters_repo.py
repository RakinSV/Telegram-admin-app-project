"""Сюжеты: одна новость, пришедшая из нескольких источников (F51).

Смысл фичи в переворачивании смысла дубля. Раньше повтор помечался
`duplicate` и исчезал. Но повтор из НЕЗАВИСИМОГО источника — это не мусор, а
подтверждение: ровно на таком материале работает редактор-фактчекер (F40) и
сравнение версий (F24). Поэтому повторы не выбрасываются, а собираются
вокруг первого пришедшего поста, и он идёт в рерайт уже с несколькими
источниками на руках.

Публикуется по-прежнему ОДИН пост — участники сюжета остаются в статусе
`duplicate` и живут как источники, а не как отдельные публикации.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from tg_repost.db.models import Post, Source, StoryCluster
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ClusterSource:
    """Один участник сюжета — как источник для рерайта и для показа владельцу."""

    post_id: int
    source_title: str | None
    link: str | None
    text: str


def attach(session: Session, new_post: Post, similar_post_id: int, similarity: float) -> int | None:
    """Присоединить `new_post` к сюжету поста `similar_post_id`.

    Возвращает id сюжета либо None, если присоединять не к чему.

    Сюжет заводится лениво — только когда появился ВТОРОЙ участник. Пока
    новость пришла из одного места, сюжета нет, и строка в таблице была бы
    просто шумом на каждый входящий пост.

    Работает в переданной сессии (вызывается внутри транзакции приёма поста),
    свою не открывает.
    """
    primary = session.get(Post, similar_post_id)
    if primary is None:
        # Похожий пост успели удалить между поиском и привязкой — не повод
        # ронять приём, просто сюжета не будет.
        return None

    now = datetime.now(timezone.utc)

    if primary.cluster_id is None:
        # Явные значения, а не полагаться на `default=`: он срабатывает при
        # INSERT, а мы правим счётчик до flush.
        cluster = StoryCluster(
            primary_post_id=primary.id, member_count=1, created_at=now, updated_at=now,
        )
        session.add(cluster)
        session.flush()  # нужен id, чтобы проставить его обоим постам
        primary.cluster_id = cluster.id
    else:
        existing = session.get(StoryCluster, primary.cluster_id)
        if existing is None:
            # Сюжет удалили из-под нас — молча не цепляем, приём не роняем.
            return None
        cluster = existing

    new_post.cluster_id = cluster.id
    cluster.member_count += 1
    cluster.updated_at = now

    logger.info(
        "Сюжет %s: +1 источник (пост %s ~ %s, сходство %.3f), всего %d",
        cluster.id, new_post.source_message_id, primary.id, similarity, cluster.member_count,
    )
    return cluster.id


def sources_for(
    cluster_id: int | None, *, exclude_post_id: int | None = None
) -> list[ClusterSource]:
    """Материалы участников сюжета — для фактчека и для показа владельцу.

    `exclude_post_id` убирает из выдачи сам рерайтимый пост: он редакции уже
    известен, и дублировать его в блоке «дополнительные источники» незачем.
    """
    if cluster_id is None:
        # Без этой проверки `Post.cluster_id == None` в SQL превратилось бы в
        # `IS NULL` и вернуло ВСЕ посты без сюжета — то есть рерайт получил бы
        # в «источники» всю базу. Поймано тестом.
        return []
    with session_scope() as session:
        rows = (
            session.query(
                Post.id, Post.original_text, Post.source_link, Source.channel_username,
            )
            .outerjoin(Source, Post.source_id == Source.id)
            .filter(Post.cluster_id == cluster_id)
            .order_by(Post.id)
            .all()
        )
    return [
        ClusterSource(
            post_id=pid, source_title=username, link=link, text=text or "",
        )
        for pid, text, link, username in rows
        if pid != exclude_post_id and (text or "").strip()
    ]


def size_of(cluster_id: int | None) -> int:
    """Сколько источников в сюжете. 0 — сюжета нет (новость пришла одна)."""
    if cluster_id is None:
        return 0
    with session_scope() as session:
        cluster = session.get(StoryCluster, cluster_id)
        return cluster.member_count if cluster else 0
