"""Метрики вовлечённости канала: ERR и ER (F53).

Ничего не собирает — считает поверх уже накопленного: `PostStat` (снимки
метрик поста, F14/F31) и `ChannelGrowthSnapshot` (снимки числа подписчиков,
F22). Это и есть весь смысл фичи: рыночная цифра, которой торгуются с
рекламодателем, получается из данных, которые у нас уже лежат.

ДВЕ МЕТРИКИ, А НЕ ОДНА — И ЭТО НАМЕРЕННО. В отрасли «ERR» называют разные
вещи: одни считают охват к подписчикам, другие вовлечённость к охвату.
Свести их в одно поле значило бы отдавать рекламодателю число, смысл
которого зависит от того, кто его читает. Поэтому обе считаются отдельно и
называются по формуле:

* `reach_rate` (ERR, Engagement Rate by Reach) — просмотры / подписчики.
  «Какая доля подписчиков реально видит пост». Именно её спрашивают при
  закупке рекламы: 100 000 подписчиков при охвате 3% стоят меньше, чем
  10 000 при 40%.
* `engagement_rate` (ER) — (реакции + пересылки) / просмотры. «Какая доля
  увидевших не пролистала мимо».

Точную формулу TGStat подтвердить не удалось — сайт не открылся из-под
текущего исходящего IP (см. разбор рынка, август 2026). Поэтому здесь
задокументированы наши формулы, а не пересказ чужих: при сверке с TGStat
сравнивать надо смысл, а не число.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from tg_repost import post_stats_repo
from tg_repost.db.models import ChannelGrowthSnapshot, Post, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)


def _percent(numerator: int, denominator: int) -> float | None:
    """Доля в процентах. `None`, если делить не на что.

    Ноль здесь был бы враньём: «0% охвата» и «мы не знаем охват» — разные
    утверждения, и второе нельзя показывать рекламодателю как первое.
    """
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 2)


def compute_reach_rate(views: int, subscribers: int) -> float | None:
    """ERR: какая доля подписчиков увидела пост, в процентах."""
    return _percent(views, subscribers)


def compute_engagement_rate(reactions: int, forwards: int, views: int) -> float | None:
    """ER: какая доля увидевших отреагировала или переслала, в процентах."""
    return _percent(reactions + forwards, views)


@dataclass(frozen=True)
class EngagementReport:
    """Отчёт по каналу за окно.

    `posts_total` против `posts_with_stats` — не украшение: если метрики
    собрались лишь у части постов, средние считаются по этой части, и знать
    об этом нужно ДО того, как цифру покажут рекламодателю.
    """

    enough_data: bool
    posts_total: int
    posts_with_stats: int
    subscribers: int | None = None
    avg_views: int | None = None
    avg_reactions: int | None = None
    avg_forwards: int | None = None
    reach_rate: float | None = None
    engagement_rate: float | None = None


def _latest_stat_per_post(session, post_ids: list[int]) -> dict[int, tuple[int, int, int]]:
    """Последний снимок метрик по каждому посту: {post_id: (views, reactions, forwards)}.

    ПОЧЕМУ НЕ SUM И НЕ AVG ПО `post_stats`. Таблица хранит СНИМКИ во времени:
    у поста, замеренного трижды, три строки — 100, 400 и 900 просмотров. Это
    один и тот же пост, набравший 900, а не 1400 просмотров у трёх постов.
    Сумма завысила бы охват в разы, среднее — занизило. Верен только
    последний снимок: счётчики Telegram монотонно растут.

    Сам отбор «последнего» живёт в `post_stats_repo` — он нужен ещё трём
    местам, и раньше был скопирован в каждое (см. docstring того модуля).
    Здесь остаётся только распаковка под нужды расчёта.
    """
    return {
        post_id: (stat.view_count or 0, stat.reaction_count or 0, stat.forward_count or 0)
        for post_id, stat in post_stats_repo.latest_stats_for(session, post_ids).items()
    }


def build_engagement_report(chat_id: int, window_days: int = 30) -> EngagementReport:
    """Посчитать ERR и ER по каналу за последние `window_days` дней."""
    since = datetime.now(timezone.utc) - timedelta(days=window_days)

    with session_scope() as session:
        post_ids = [
            row[0]
            for row in session.query(Post.id)
            .filter(
                Post.status == PostStatus.POSTED,
                Post.posted_chat_id == chat_id,
                Post.posted_at >= since,
            )
            .all()
        ]
        stats = _latest_stat_per_post(session, post_ids)

        # Подписчики — последний снимок, а не первый: ERR отвечает на вопрос
        # «сколько людей увидит пост, если разместиться СЕЙЧАС».
        subs_row = (
            session.query(ChannelGrowthSnapshot.subscriber_count)
            .filter(ChannelGrowthSnapshot.chat_id == chat_id)
            # Тай-брейк по `id` — та же причина, что в `_latest_stat_per_post`:
            # при совпадении меток времени порядок иначе не определён, и код
            # мог вернуть УСТАРЕВШЕЕ число подписчиков, занизив или завысив ERR.
            .order_by(
                ChannelGrowthSnapshot.captured_at.desc(),
                ChannelGrowthSnapshot.id.desc(),
            )
            .first()
        )
        subscribers = subs_row[0] if subs_row else None

    if not stats:
        logger.info(
            "F53: по каналу %s за %d дн. нет ни одного поста с метриками "
            "(опубликовано %d)", chat_id, window_days, len(post_ids),
        )
        return EngagementReport(
            enough_data=False,
            posts_total=len(post_ids),
            posts_with_stats=0,
            subscribers=subscribers,
        )

    measured = len(stats)
    total_views = sum(v for v, _, _ in stats.values())
    total_reactions = sum(r for _, r, _ in stats.values())
    total_forwards = sum(f for _, _, f in stats.values())

    avg_views = total_views // measured
    return EngagementReport(
        enough_data=True,
        posts_total=len(post_ids),
        posts_with_stats=measured,
        subscribers=subscribers,
        avg_views=avg_views,
        avg_reactions=total_reactions // measured,
        avg_forwards=total_forwards // measured,
        # ERR считается по СРЕДНЕМУ охвату поста, а не по сумме за месяц:
        # сумма просмотров всех постов к числу подписчиков дала бы сотни
        # процентов и не значила бы ничего.
        reach_rate=compute_reach_rate(avg_views, subscribers) if subscribers else None,
        engagement_rate=compute_engagement_rate(
            total_reactions, total_forwards, total_views
        ),
    )
