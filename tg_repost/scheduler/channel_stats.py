"""Статистика канала через MTProto Stats API (F56).

СТРУКТУРНОЕ ПРЕИМУЩЕСТВО, А НЕ ПРОСТО ФИЧА. `stats.getBroadcastStats` — метод
уровня MTProto; в Bot API его нет вообще, поэтому боты-конкуренты этих данных
не получат, не сменив архитектуру целиком. Нам же ничего менять не надо:
юзер-сессия Telethon уже работает в listener (F02).

Главное, что отсюда достаётся, — `enabled_notifications`: доля подписчиков с
включёнными уведомлениями. Её падение означает, что люди ещё числятся
подписчиками, но уже отключили звук и не читают. Это отток за неделю до
самой отписки, и никаким другим способом он не виден.

ЧТО В ЭТУ ВЕРСИЮ НЕ ВОШЛО (осознанно, не забыто):

* **графики** (`growth_graph`, `mute_graph`, `top_hours_graph` и прочие).
  Telegram отдаёт их как `StatsGraphAsync` — это токен, который надо
  догружать вторым вызовом `stats.loadAsyncGraph`, а потом разбирать JSON
  чужого формата. Своя история из скалярных снимков даёт ту же динамику
  проще и надёжнее — ровно как это уже устроено в F22.
* **`stats.getMessagePublicForwards`** (кто репостнул пост — список для
  взаимопиара). Отдельный вызов на каждое сообщение, то есть отдельный
  бюджет запросов и свой антибан-режим. Просится отдельной задачей.
* **мегагруппы.** У них другой метод (`stats.getMegagroupStats`) и другой
  набор полей. Сейчас такой чат просто пропускается с понятным сообщением,
  а не падает.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient
from telethon.tl.functions.stats import GetBroadcastStatsRequest

from tg_repost.db.models import ChannelStatsSnapshot, TargetGroup
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)


@dataclass
class CollectReport:
    """Что вышло из прохода сбора.

    `no_rights` отделён от `failed` не для красоты: отсутствие прав
    администратора — это не сбой, а состояние, которое ЧИНИТ ВЛАДЕЛЕЦ, выдав
    боту права. Сваленное в общий счётчик ошибок, оно выглядит как «что-то
    сломалось» и живёт в логах годами.
    """

    collected: int = 0
    no_rights: list[int] = field(default_factory=list)
    not_a_channel: list[int] = field(default_factory=list)
    failed: list[int] = field(default_factory=list)


def _scalar(container: object, name: str) -> int | None:
    """`current` из `StatsAbsValueAndPrev`-подобного поля.

    Telegram отдаёт пару «сейчас/раньше»; «раньше» мы не храним — своя
    история точнее, чем чужое окно сравнения неизвестной длины.
    """
    value = getattr(container, name, None)
    current = getattr(value, "current", None)
    return int(current) if current is not None else None


def _percent(container: object, name: str) -> float | None:
    """Процент из `StatsPercentValue` (`part` от `total`).

    Telegram отдаёт долю как две абсолютные величины, а не как готовый
    процент. Деление на ноль здесь реально: у канала без подписчиков
    `total` равен нулю.
    """
    value = getattr(container, name, None)
    part = getattr(value, "part", None)
    total = getattr(value, "total", None)
    if part is None or not total:
        return None
    return round(part / total * 100, 2)


def parse_broadcast_stats(stats: object) -> dict[str, float | int | None]:
    """Ответ `stats.getBroadcastStats` → поля снимка (чистая функция).

    Отдельно от сетевого вызова, чтобы разбор можно было проверить тестом,
    не поднимая Telegram.
    """
    return {
        "views_per_post": _scalar(stats, "views_per_post"),
        "shares_per_post": _scalar(stats, "shares_per_post"),
        "reactions_per_post": _scalar(stats, "reactions_per_post"),
        "notifications_enabled_pct": _percent(stats, "enabled_notifications"),
    }


async def collect_channel_stats(client: TelegramClient) -> CollectReport:
    """Снять статистику активных целевых каналов. Требует прав администратора."""
    report = CollectReport()

    with session_scope() as session:
        chat_ids = [
            row[0]
            for row in session.query(TargetGroup.chat_id)
            .filter(TargetGroup.is_active.is_(True))
            .all()
        ]

    for chat_id in chat_ids:
        try:
            entity = await client.get_entity(chat_id)
            stats = await client(GetBroadcastStatsRequest(channel=entity))
        except Exception as exc:  # noqa: BLE001 — Telethon кидает разные типы
            text = str(exc)
            # Разбор по тексту, а не по классу исключения: Telethon поднимает
            # ChatAdminRequiredError, но точный класс зависит от версии, а
            # ловить голый Exception и молчать — как раз то, из-за чего фича
            # потом «не работает» без объяснений.
            if "CHAT_ADMIN_REQUIRED" in text or "ADMIN" in text.upper():
                report.no_rights.append(chat_id)
                logger.warning(
                    "F56: нет прав администратора в %s — статистика канала "
                    "недоступна. Выдай боту права администратора.", chat_id,
                )
            elif "BROADCAST_REQUIRED" in text or "MEGAGROUP" in text.upper():
                report.not_a_channel.append(chat_id)
                logger.info(
                    "F56: %s — не канал (мегагруппа). У неё другой метод "
                    "статистики, он в эту версию не вошёл.", chat_id,
                )
            else:
                report.failed.append(chat_id)
                logger.warning("F56: не удалось снять статистику %s: %s", chat_id, text)
            continue

        fields = parse_broadcast_stats(stats)
        with session_scope() as session:
            session.add(ChannelStatsSnapshot(chat_id=chat_id, **fields))
        report.collected += 1

    logger.info(
        "F56: снимков собрано %d, без прав %d, не каналы %d, ошибок %d",
        report.collected, len(report.no_rights),
        len(report.not_a_channel), len(report.failed),
    )
    return report


@dataclass(frozen=True)
class MuteTrend:
    """Динамика доли включённых уведомлений по каналу."""

    enough_data: bool
    snapshots: int
    first_pct: float | None = None
    last_pct: float | None = None
    delta: float | None = None

    @property
    def is_alarming(self) -> bool:
        """Доля включённых уведомлений ПАДАЕТ — тихий отток.

        Порог в один процентный пункт, а не любое падение: колебания на
        десятых долях — это шум округления, и поднимать по ним тревогу
        значит приучить владельца не смотреть на предупреждения.
        """
        return self.delta is not None and self.delta <= -1.0


def mute_trend(chat_id: int, window_days: int = 30) -> MuteTrend:
    """Как изменилась доля включённых уведомлений за период.

    Отрицательная дельта — люди отключают звук. Это и есть отток до отписки:
    число подписчиков ещё не падает, а читать уже перестали.
    """
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    with session_scope() as session:
        rows = (
            session.query(
                ChannelStatsSnapshot.notifications_enabled_pct,
                ChannelStatsSnapshot.captured_at,
                ChannelStatsSnapshot.id,
            )
            .filter(
                ChannelStatsSnapshot.chat_id == chat_id,
                ChannelStatsSnapshot.captured_at >= since,
                ChannelStatsSnapshot.notifications_enabled_pct.isnot(None),
            )
            # Тай-брейк по `id` — та же причина, что во всей работе с
            # метриками: при совпадении меток времени порядок иначе не
            # определён (см. `post_stats_repo`).
            .order_by(ChannelStatsSnapshot.captured_at.asc(), ChannelStatsSnapshot.id.asc())
            .all()
        )

    if len(rows) < 2:
        return MuteTrend(enough_data=False, snapshots=len(rows))

    first = rows[0][0]
    last = rows[-1][0]
    return MuteTrend(
        enough_data=True,
        snapshots=len(rows),
        first_pct=first,
        last_pct=last,
        delta=round(last - first, 2),
    )
