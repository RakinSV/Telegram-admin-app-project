"""Повтор выстреливших постов — recycling (F55).

Подсмотрено у Publer и Onlypult: удачный пост ставится в очередь повторно
через заданный срок. Почти бесплатный охват из уже проверенного контента —
данные для отбора топа и так лежат в метриках (F14/F31), не хватало только
постановки повтора в очередь.

ПОВТОР ИДЁТ В МОДЕРАЦИЮ, А НЕ В ПУБЛИКАЦИЮ. Создаётся `Post(kind=RECYCLE,
status=REWRITTEN)` — дальше обычный пайплайн F05/F07/F08, то есть владелец
видит превью и жмёт «одобрить». Авто-повтор без подтверждения превращает
ленту в самоповтор быстрее, чем владелец успевает это заметить.

Четыре правила отбора, каждое закрывает свой способ испортить ленту:

1. **только `kind=SOURCE`** — иначе повтор сам станет кандидатом на повтор, и
   один и тот же текст будет крутиться бесконечно;
2. **не повторять дважды** — наличие поста с `recycled_from_id == X` закрывает
   X навсегда;
3. **минимальный возраст** — вчерашнее аудитория ещё помнит, и повтор читается
   как сбой, а не как напоминание;
4. **порог просмотров** — повторяем выстрелившее, а не всё подряд.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tg_repost.config import get_settings
from tg_repost.db.models import Post, PostKind, PostStat, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)


def select_recycle_candidates(
    *,
    window_days: int,
    min_age_days: int,
    min_views: int,
    top_n: int,
) -> list[int]:
    """id постов, которые стоит повторить — по убыванию просмотров.

    Возвращает именно id, а не ORM-объекты: между отбором и созданием повтора
    открывается новая транзакция, и тащить через неё отсоединённые инстансы
    незачем.
    """
    now = datetime.now(timezone.utc)
    oldest = now - timedelta(days=window_days)
    newest = now - timedelta(days=min_age_days)

    if newest <= oldest:
        # Окно схлопнулось: минимальный возраст больше окна поиска, кандидатов
        # не будет никогда. Молчать здесь нельзя — со стороны это выглядит как
        # «фича не работает», хотя на деле настройки противоречат друг другу.
        logger.warning(
            "F55: окно пустое — RECYCLE_MIN_AGE_DAYS=%d не меньше "
            "RECYCLE_WINDOW_DAYS=%d, кандидатов не будет",
            min_age_days, window_days,
        )
        return []

    with session_scope() as session:
        # Правило 2: id оригиналов, которые уже повторяли. Отдельный запрос,
        # а не NOT EXISTS в основном — список короткий, а читаемость важнее.
        already = {
            row[0]
            for row in session.query(Post.recycled_from_id)
            .filter(Post.recycled_from_id.isnot(None))
            .all()
        }

        posts = (
            session.query(Post.id)
            .filter(
                # Правило 1: только оригиналы. Без этого фильтра повтор попал
                # бы в кандидаты на следующем проходе.
                Post.kind == PostKind.SOURCE,
                Post.status == PostStatus.POSTED,
                Post.posted_at >= oldest,
                # Правило 3: достаточно «остыл».
                Post.posted_at <= newest,
            )
            .all()
        )
        candidates = [pid for (pid,) in posts if pid not in already]
        if not candidates:
            return []

        rows: list[tuple[int, int]] = []
        for post_id in candidates:
            last = (
                session.query(PostStat)
                .filter(PostStat.post_id == post_id)
                # Тай-брейк по `id` — см. F53: при совпадении меток времени
                # порядок иначе не определён.
                .order_by(PostStat.captured_at.desc(), PostStat.id.desc())
                .first()
            )
            views = last.view_count if last and last.view_count is not None else 0
            # Правило 4: порог. Пост без единого снимка метрик считается за 0
            # просмотров и при любом положительном пороге не проходит — это
            # верно: «не знаем, выстрелил ли» не повод повторять.
            if views >= min_views:
                rows.append((post_id, views))

    # При равенстве просмотров — меньший id первым, чтобы порядок был
    # воспроизводимым (тот же приём, что в `digest.rank_posts_by_views`).
    rows.sort(key=lambda r: (-r[1], r[0]))
    return [post_id for post_id, _ in rows[:top_n]]


def create_recycle_post(original_id: int) -> int | None:
    """Поставить повтор оригинала в очередь модерации. Возвращает id повтора.

    `None` — оригинал исчез или у него нет текста для публикации.
    """
    with session_scope() as session:
        original = session.get(Post, original_id)
        if original is None:
            logger.warning("F55: оригинал #%s исчез между отбором и созданием", original_id)
            return None

        text = original.rewritten_text or original.original_text
        if not text:
            logger.warning("F55: у оригинала #%s нет текста — повтор невозможен", original_id)
            return None

        repeat = Post(
            kind=PostKind.RECYCLE,
            source_id=original.source_id,
            source_link=original.source_link,
            original_text=original.original_text,
            rewritten_text=text,
            media_path=original.media_path,
            recycled_from_id=original.id,
            # Статус REWRITTEN, а не NEW: текст уже готов, платить за второй
            # рерайт того же материала незачем.
            status=PostStatus.REWRITTEN,
        )
        # content_hash НАМЕРЕННО не копируется: он служит дедупликации на
        # приёме, и повтор с тем же хэшем был бы отсеян как «точный дубль» —
        # то есть фича ломала бы сама себя. Повтор в приём и не заходит,
        # но копия хэша сделала бы будущую ошибку тихой.
        session.add(repeat)
        session.flush()
        logger.info("F55: повтор #%d поставлен в модерацию (оригинал #%d)", repeat.id, original.id)
        return repeat.id


def run_recycle_job() -> int:
    """Джоб планировщика: отобрать кандидатов и поставить повторы. Сколько создано."""
    settings = get_settings()
    if not settings.recycle_enabled:
        return 0

    candidates = select_recycle_candidates(
        window_days=settings.recycle_window_days,
        min_age_days=settings.recycle_min_age_days,
        min_views=settings.recycle_min_views,
        top_n=settings.recycle_top_n,
    )
    if not candidates:
        logger.debug("F55: кандидатов на повтор нет")
        return 0

    created = sum(1 for post_id in candidates if create_recycle_post(post_id) is not None)
    logger.info("F55: поставлено повторов: %d из %d кандидатов", created, len(candidates))
    return created
