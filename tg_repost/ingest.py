"""Единый приём входящего поста: фильтр → дедуп → сюжет → очередь.

Зачем отдельный модуль. Эта логика жила в двух местах — в
`telegram/listener.py` и в `rss/poller.py`, — и копии разошлись: RSS-ветка
считала `content_hash`, но НИКОГДА его не сверяла, а семантического
дубль-чека там не было вовсе. То есть одна и та же новость из пяти лент
давала пять постов. Пока правила приёма скопированы, они будут расходиться
снова, поэтому решение здесь одно на всех, а вызывающие отвечают только за
то, что у них действительно различается:

* как узнать «я уже видел это сообщение» (у Telegram — `message_id`, у RSS —
  `guid` ленты);
* откуда взять текст и ссылку.

Эмбеддинг считается ВНЕ этого модуля: это сетевой вызов, и держать открытую
транзакцию БД на время похода к провайдеру нельзя.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from tg_repost import clusters_repo
from tg_repost.config import get_settings
from tg_repost.db.models import Post, PostStatus, Source
from tg_repost.dedup.hash_dedup import content_hash
from tg_repost.dedup.semantic import find_similar_post, pack_embedding
from tg_repost.filtering import check_keywords, resolve_filters
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class IngestResult:
    """Что стало с постом на приёме."""

    post_id: int | None
    status: PostStatus
    reason: str | None = None
    cluster_id: int | None = None

    @property
    def queued(self) -> bool:
        """Пост встал в очередь на рерайт (а не отсеян и не признан дублем)."""
        return self.status == PostStatus.NEW


def filters_for_source(source_id: int | None) -> tuple[list[str], list[str]]:
    """Итоговые списки слов для источника (F54): глобальные + его собственные.

    Открывает собственную короткую сессию — вызывается из `compute_embedding`,
    то есть ДО основной транзакции и вне её.
    """
    settings = get_settings()
    if source_id is None:
        return settings.filter_stop_words, settings.filter_required_words

    from tg_repost.db.session import session_scope

    with session_scope() as session:
        source = session.get(Source, source_id)
        return resolve_filters(
            source, settings.filter_stop_words, settings.filter_required_words
        )


async def compute_embedding(text: str, source_id: int | None = None) -> list[float] | None:
    """Эмбеддинг оригинала для семантического дубль-чека, если он включён.

    Отдельная функция, потому что вызывать её надо ДО открытия транзакции:
    внутри поход в сеть, а держать соединение с БД на это время нельзя.
    None — эмбеддинги выключены, пост всё равно отсеется фильтром или
    провайдер не ответил (последнее не повод терять пост: без эмбеддинга он
    просто не участвует в семантическом сравнении).
    """
    settings = get_settings()
    if not settings.semantic_dedup_enabled:
        return None

    # Фильтр слов прогоняется здесь ВТОРОЙ раз (первый — в `ingest_post`), и
    # это сознательно: он чистый и дешёвый, а платный вызов эмбеддингов для
    # поста, который всё равно отсеется по стоп-слову, — выброшенные деньги.
    # Раньше такая экономия была только в Telegram-ветке; теперь она общая.
    #
    # Списки берутся С УЧЁТОМ источника (F54). Если бы здесь остались только
    # глобальные, экономия перестала бы работать ровно для тех лент, ради
    # которых фича и делалась: шумной ленте задали свои стоп-слова, а деньги
    # за эмбеддинги её постов продолжали бы уходить.
    stop_words, required_words = filters_for_source(source_id)
    if not check_keywords(text, stop_words, required_words).passed:
        return None
    # Импорт внутри: модуль рерайтера тянет за собой http-клиент, а `ingest`
    # импортируется и там, где рерайт не нужен (например, в тестах приёма).
    from tg_repost.rewriter.client import get_rewriter

    try:
        return await get_rewriter().embed(text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Не удалось получить эмбеддинг: %s", exc)
        return None


def ingest_post(
    session: Session,
    *,
    source_id: int | None,
    text: str,
    source_link: str | None,
    source_message_id: int | None = None,
    embedding: list[float] | None = None,
) -> IngestResult:
    """Принять пост: отфильтровать, проверить на дубль, собрать сюжет.

    Работает в ПЕРЕДАННОЙ сессии — вызывающий сам управляет транзакцией и
    может в той же транзакции проверить «уже видел это сообщение».

    Порядок проверок не случаен: сначала дешёвый фильтр слов, затем точный
    хэш, и только потом сравнение векторов — чтобы не гонять косинусы по
    всей недавней истории для поста, который отсеется по стоп-слову.
    """
    settings = get_settings()
    digest = content_hash(text)

    post = Post(
        source_id=source_id,
        source_message_id=source_message_id,
        source_link=source_link,
        original_text=text,
        content_hash=digest,
        status=PostStatus.NEW,
    )
    if embedding is not None:
        post.embedding = pack_embedding(embedding)

    # F03 + F54 — фильтр ключевых слов: глобальные списки плюс собственные
    # списки источника, если он их задал.
    source = session.get(Source, source_id) if source_id is not None else None
    stop_words, required_words = resolve_filters(
        source, settings.filter_stop_words, settings.filter_required_words
    )
    filter_result = check_keywords(text, stop_words, required_words)
    if not filter_result.passed:
        post.set_status(PostStatus.FILTERED_OUT, reason=filter_result.reason)
        session.add(post)
        session.flush()
        return IngestResult(post.id, PostStatus.FILTERED_OUT, filter_result.reason)

    # F04 — точный дубль по хэшу. Отсекаем сразу: это буквальный копипаст,
    # добавлять его в сюжет как «независимое подтверждение» было бы враньём.
    dup = (
        session.query(Post.id)
        .filter(
            Post.content_hash == digest,
            Post.status != PostStatus.DUPLICATE,
            Post.status != PostStatus.FILTERED_OUT,
        )
        .first()
    )
    if dup:
        reason = "точный дубль по хэшу"
        post.set_status(PostStatus.DUPLICATE, reason=reason)
        session.add(post)
        session.flush()
        return IngestResult(post.id, PostStatus.DUPLICATE, reason)

    # F13 + F51 — семантический повтор. Это и есть «та же новость своими
    # словами»: публиковать второй раз не надо, но и выбрасывать жалко —
    # цепляем к сюжету как дополнительный источник.
    if embedding is not None:
        similar = find_similar_post(
            session,
            embedding,
            threshold=settings.semantic_similarity_threshold,
            window_days=settings.dedup_window_days,
        )
        if similar is not None:
            sim_id, sim_score = similar
            post.set_status(PostStatus.DUPLICATE, reason=f"сюжет: похоже на #{sim_id}")
            session.add(post)
            session.flush()
            cluster_id = clusters_repo.attach(session, post, sim_id, sim_score)
            reason = (
                f"источник сюжета #{cluster_id} (похоже на #{sim_id}, {sim_score:.3f})"
                if cluster_id
                else f"семантический дубль #{sim_id} (sim={sim_score:.3f})"
            )
            post.status_reason = reason
            return IngestResult(post.id, PostStatus.DUPLICATE, reason, cluster_id)

    session.add(post)
    session.flush()
    return IngestResult(post.id, PostStatus.NEW)
