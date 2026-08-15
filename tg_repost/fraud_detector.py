"""Детектор накрутки по кривой роста (F60).

Две задачи владельца: проверять промо-закупки, за которые платишь, и
доказывать рекламодателю, что свой рост органический.

ПОЧЕМУ ЭТО МОЖЕМ МЫ, А РАЗОВЫЕ ЧЕКЕРЫ — НЕТ. У бота, которому скормили ссылку
на канал, есть один снимок: сегодняшние подписчики и охваты. Накрутка видна
не в точке, а в ФОРМЕ кривой, а форма нужна за недели. У нас история
собирается с первого дня (F22), у чекера её нет и взять неоткуда.

ДВА СИГНАЛА, А НЕ ТРИ. В методиках обычно называют три: «пила», рост без
охватов и ступеньки в нерабочее время. Третий мы НЕ считаем: снимки
подписчиков делаются раз в несколько часов, и разрешения по часам у нас
попросту нет. Посчитать его «примерно» значило бы выдать шум за улику —
а на этих цифрах человек решает, платить ли за размещение.

ФОРМУЛИРОВКИ ОСТОРОЖНЫЕ НАМЕРЕННО. Детектор говорит «есть признаки», а не
«накрутка»: он видит форму кривой, а не намерение. Резкий приход и уход
бывает и у честного канала — например, после виральной публикации.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from tg_repost import engagement_repo
from tg_repost.db.models import ChannelGrowthSnapshot
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

# Минимум снимков, чтобы вообще говорить о форме кривой. По трём точкам
# «пилу» от обычного колебания не отличить.
MIN_SNAPSHOTS = 6

# Прирост считается ВСПЛЕСКОМ, если он больше этой доли от общего числа
# подписчиков за один интервал между снимками.
SPIKE_SHARE = 0.05
# Всплеск считается «пилой», если следом ушло не меньше этой доли пришедших.
DROPBACK_SHARE = 0.5
# На сколько интервалов вперёд смотрим отток после всплеска.
DROPBACK_WINDOW = 4

# Рост подписчиков считается подозрительным, если он заметный, а охваты за
# то же время не выросли. Порог по подписчикам — чтобы не тревожиться на
# росте в пару процентов, который ничего не значит.
GROWTH_THRESHOLD = 0.15
# Насколько охват должен отставать. 0.0 — охваты вообще не выросли.
REACH_LAG = 0.0


@dataclass(frozen=True)
class Finding:
    """Одна находка: что увидели и на чём основано."""

    code: str
    detail: str


@dataclass(frozen=True)
class FraudReport:
    enough_data: bool
    snapshots: int
    findings: tuple[Finding, ...] = ()

    @property
    def looks_suspicious(self) -> bool:
        return bool(self.findings)


def detect_sawtooth(series: list[tuple[datetime, int]]) -> Finding | None:
    """«Пила»: резкий приход и такой же быстрый уход (чистая функция).

    Так выглядит закупка ботов, которых потом снимают: подписчиков стало
    больше, через день — почти столько же, сколько было.
    """
    if len(series) < 3:
        return None

    ordered = sorted(series, key=lambda item: item[0])
    for index in range(1, len(ordered)):
        previous, current = ordered[index - 1][1], ordered[index][1]
        gain = current - previous
        if previous <= 0 or gain <= 0:
            continue
        if gain / previous < SPIKE_SHARE:
            continue

        window = ordered[index + 1 : index + 1 + DROPBACK_WINDOW]
        if not window:
            continue
        lowest = min(value for _, value in window)
        lost = current - lowest
        if lost >= gain * DROPBACK_SHARE:
            return Finding(
                code="sawtooth",
                detail=(
                    f"скачок +{gain} ({ordered[index][0]:%Y-%m-%d}), "
                    f"из них ушло {lost} в ближайшие дни"
                ),
            )
    return None


def detect_growth_without_reach(
    subs_first: int, subs_last: int, views_first: int | None, views_last: int | None
) -> Finding | None:
    """Подписчиков прибавилось, а читать больше не стали (чистая функция).

    Самый показательный сигнал: живой подписчик хоть иногда открывает канал,
    и охват растёт вместе с аудиторией. Если аудитория выросла на четверть, а
    охваты стоят — прибавка не читает.
    """
    if subs_first <= 0 or views_first is None or views_last is None:
        return None
    if views_first <= 0:
        return None

    subs_growth = (subs_last - subs_first) / subs_first
    if subs_growth < GROWTH_THRESHOLD:
        return None

    views_growth = (views_last - views_first) / views_first
    if views_growth > REACH_LAG:
        return None

    return Finding(
        code="growth_without_reach",
        detail=(
            f"подписчиков +{subs_growth:.0%}, охват {views_growth:+.0%} "
            f"({views_first} → {views_last})"
        ),
    )


def analyze(chat_id: int, window_days: int = 30) -> FraudReport:
    """Проверить канал на признаки накрутки за период."""
    since = datetime.now(timezone.utc) - timedelta(days=window_days)

    with session_scope() as session:
        rows = (
            session.query(
                ChannelGrowthSnapshot.captured_at,
                ChannelGrowthSnapshot.subscriber_count,
            )
            .filter(
                ChannelGrowthSnapshot.chat_id == chat_id,
                ChannelGrowthSnapshot.captured_at >= since,
            )
            # Тай-брейк по `id` — при совпадении меток порядок иначе не
            # определён (та же причина, что во всей работе с метриками).
            .order_by(
                ChannelGrowthSnapshot.captured_at.asc(),
                ChannelGrowthSnapshot.id.asc(),
            )
            .all()
        )

    series = [(captured_at, count) for captured_at, count in rows]
    if len(series) < MIN_SNAPSHOTS:
        return FraudReport(enough_data=False, snapshots=len(series))

    findings: list[Finding] = []

    sawtooth = detect_sawtooth(series)
    if sawtooth is not None:
        findings.append(sawtooth)

    # Охваты берём двумя половинами окна: сравнивать «сейчас» с «когда-то»
    # честнее, чем с одним постом, который мог быть удачным или провальным.
    older = engagement_repo.build_engagement_report(chat_id, window_days)
    recent = engagement_repo.build_engagement_report(chat_id, window_days // 2 or 1)
    growth = detect_growth_without_reach(
        subs_first=series[0][1],
        subs_last=series[-1][1],
        views_first=older.avg_views,
        views_last=recent.avg_views,
    )
    if growth is not None:
        findings.append(growth)

    if findings:
        logger.info(
            "F60: у канала %s признаки накрутки: %s",
            chat_id, ", ".join(f.code for f in findings),
        )
    return FraudReport(
        enough_data=True, snapshots=len(series), findings=tuple(findings),
    )
