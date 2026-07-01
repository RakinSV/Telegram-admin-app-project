"""Умное расписание публикаций — каркас (F19).

Анализирует накопленную статистику просмотров (F14) и считает, в какие часы
суток опубликованные посты набирают больше всего просмотров. НЕ применяет
результат автоматически к `POSTING_SLOTS` — выдаёт только рекомендацию
(команда бота `/best_times`), пока данных недостаточно для надёжного вывода
(порог — `SMART_SCHEDULE_MIN_POSTS`). Автоприменение — следующий шаг, когда
накопится реальная статистика (см. план, Фаза 4).

Ограничение: час публикации берётся в UTC (`Post.posted_at`), а не в часовом
поясе аудитории — в конфиге сейчас нет настройки таймзоны канала. Это сужает
точность рекомендации, но не меняет её механику; добавить TARGET_TIMEZONE —
тривиальное расширение на будущее, если понадобится.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from tg_repost.config import get_settings
from tg_repost.db.models import Post, PostKind, PostStat, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ScheduleRecommendation:
    """Результат расчёта рекомендованных слотов публикации."""

    enough_data: bool
    posts_analyzed: int
    min_required: int
    recommended_slots: list[str]


def aggregate_views_by_hour(samples: list[tuple[int, int]]) -> dict[int, int]:
    """Просуммировать просмотры по часу публикации (чистая функция).

    `samples` — список (hour_of_day 0-23, views).
    """
    totals: dict[int, int] = {}
    for hour, views in samples:
        if not 0 <= hour <= 23:
            continue
        totals[hour] = totals.get(hour, 0) + max(0, views)
    return totals


def recommend_hours(hourly_totals: dict[int, int], top_n: int) -> list[str]:
    """Топ-N часов по суммарным просмотрам как "HH:00" (чистая функция).

    При равенстве просмотров — меньший час первым (стабильность для тестов).
    """
    ranked = sorted(hourly_totals.items(), key=lambda kv: (-kv[1], kv[0]))
    return [f"{hour:02d}:00" for hour, _ in ranked[:top_n]]


def compute_recommended_slots(window_days: int, top_n: int, min_posts: int) -> ScheduleRecommendation:
    """Посчитать рекомендованные слоты на основе постов за период."""
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    with session_scope() as session:
        rows = (
            session.query(Post.id, Post.posted_at, PostStat.view_count)
            .join(PostStat, PostStat.post_id == Post.id)
            .filter(
                Post.kind == PostKind.SOURCE,
                Post.status == PostStatus.POSTED,
                Post.posted_at >= since,
            )
            .all()
        )

    # Берём по одному (макс.) снимку на пост — последний по времени снимка
    # пришлось бы агрегировать отдельным запросом; для простоты каркаса
    # используем все снимки в окне (более свежие посты дают больше снимков,
    # это сознательное упрощение v1, см. докстринг модуля).
    #
    # ВАЖНО: SQLite не сохраняет tzinfo — значения, записанные как
    # datetime.now(timezone.utc) (см. publisher.py), при чтении возвращаются
    # naive. Весь код пишет posted_at только в UTC (единственное место
    # присвоения — publisher.py), поэтому здесь безопасно и нужно
    # ДОБАВИТЬ метку tzinfo=UTC через `.replace()`, а НЕ конвертировать через
    # `.astimezone()` — последний трактует naive datetime как ЛОКАЛЬНОЕ время
    # сервера и сдвигает час на величину локального офсета (баг, найденный
    # код-ревью: 23:00 UTC превращалось в 18 при офсете -5).
    samples = [
        (posted_at.replace(tzinfo=timezone.utc).hour, views or 0)
        for _post_id, posted_at, views in rows
        if posted_at is not None
    ]
    # Различаем по id поста, а НЕ по значению posted_at — несколько постов с
    # одинаковым (до секунды) временем публикации иначе схлопнулись бы в один
    # (нашёл собственный регрессионный тест с пачкой постов в одну секунду).
    posts_analyzed = len({post_id for post_id, posted_at, _ in rows if posted_at is not None})

    if posts_analyzed < min_posts:
        return ScheduleRecommendation(
            enough_data=False,
            posts_analyzed=posts_analyzed,
            min_required=min_posts,
            recommended_slots=[],
        )

    hourly = aggregate_views_by_hour(samples)
    slots = recommend_hours(hourly, top_n)
    return ScheduleRecommendation(
        enough_data=True,
        posts_analyzed=posts_analyzed,
        min_required=min_posts,
        recommended_slots=slots,
    )


def best_times_summary() -> str:
    """Текст для команды бота `/best_times`."""
    settings = get_settings()
    rec = compute_recommended_slots(
        settings.smart_schedule_window_days,
        settings.smart_schedule_top_n,
        settings.smart_schedule_min_posts,
    )
    if not rec.enough_data:
        return (
            f"📈 Недостаточно данных для рекомендации: проанализировано "
            f"{rec.posts_analyzed} постов, нужно минимум {rec.min_required}.\n"
            f"Накопи больше статистики (F14) и попробуй снова."
        )
    slots_str = ", ".join(rec.recommended_slots) or "—"
    return (
        f"📈 Рекомендуемые часы публикации (по {rec.posts_analyzed} постам, "
        f"UTC): {slots_str}\n"
        f"Применить можно кнопкой «Применить сейчас» на /stats/best-times в "
        f"веб-админке, либо включить автоприменение раз в сутки в настройках."
    )


def apply_recommended_slots(rec: ScheduleRecommendation) -> bool:
    """Применить рекомендованные слоты к `posting_slots`, если данных
    достаточно и рекомендация реально отличается от текущих слотов.

    Возвращает True, если слоты были изменены (вызывающий код должен
    вызвать `resync_scheduler_jobs()`, чтобы пересобрать `slot_*`-джобы —
    здесь этого не делаем: у вызова два разных источника — периодическая
    джоба и ручная кнопка «Применить сейчас», каждый сам решает, когда и
    как резинкать планировщик).
    """
    if not rec.enough_data or not rec.recommended_slots:
        return False
    from tg_repost.webui import settings_store

    settings = get_settings()
    if sorted(rec.recommended_slots) == sorted(settings.posting_slots):
        return False
    settings_store.save_setting("posting_slots", rec.recommended_slots, "csv_list")
    logger.info(
        "F19: слоты публикации обновлены автоматически: %s -> %s",
        settings.posting_slots, rec.recommended_slots,
    )
    return True


async def auto_apply_slots_job() -> None:
    """Периодическая джоба планировщика (раз в сутки, см. `webui/
    supervisor.py::_sync_jobs`) — применяет рекомендацию к `posting_slots`,
    если включена настройка `smart_schedule_auto_apply`, и сразу
    пересинхронизирует `slot_*`-джобы под новые значения."""
    settings = get_settings()
    if not settings.smart_schedule_auto_apply:
        return
    rec = compute_recommended_slots(
        settings.smart_schedule_window_days, settings.smart_schedule_top_n,
        settings.smart_schedule_min_posts,
    )
    if apply_recommended_slots(rec):
        # Локальный импорт — resync_scheduler_jobs живёт в webui.supervisor,
        # который сам импортирует эту джобу для регистрации в APScheduler
        # (см. _sync_jobs) — импорт на уровне модуля создал бы цикл.
        from tg_repost.webui.supervisor import resync_scheduler_jobs

        await resync_scheduler_jobs()
