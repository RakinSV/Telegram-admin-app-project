"""Growth-трекер — каркас (F22).

Периодически снимает число подписчиков активных целевых каналов через
Telethon и пишет в `channel_growth_snapshots`. Отчёт (`/growth`) показывает
прирост за период и сколько постов какого стиля вышло за это время —
СЧЁТЧИК, а не статистическая корреляция: на малом объёме данных вычислять
псевдо-корреляцию было бы вводящим в заблуждение (см. план, Фаза 4 — F22
явно зависит от накопленного объёма). Полноценная корреляционная модель —
следующий шаг, когда снимков и постов станет достаточно много.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient
from telethon.tl.functions.channels import GetFullChannelRequest

from tg_repost.config import get_settings
from tg_repost.db.models import (
    ChannelGrowthSnapshot,
    Post,
    PostKind,
    PostStatus,
    Source,
    TargetGroup,
)
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)


async def collect_growth_snapshot(client: TelegramClient) -> int:
    """Снять число подписчиков активных целевых каналов. Возвращает число снимков."""
    with session_scope() as session:
        chat_ids = [
            row[0]
            for row in session.query(TargetGroup.chat_id)
            .filter(TargetGroup.is_active.is_(True))
            .all()
        ]

    captured = 0
    for chat_id in chat_ids:
        try:
            entity = await client.get_entity(chat_id)
            full = await client(GetFullChannelRequest(entity))
            count = getattr(full.full_chat, "participants_count", None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось получить число подписчиков %s: %s", chat_id, exc)
            continue
        if count is None:
            continue
        with session_scope() as session:
            session.add(ChannelGrowthSnapshot(chat_id=chat_id, subscriber_count=count))
        captured += 1

    logger.info("Growth-снимок: собрано %d из %d каналов", captured, len(chat_ids))
    return captured


def compute_growth_delta(
    snapshots: list[tuple[datetime, int]],
) -> tuple[int, int, int] | None:
    """(первое значение, последнее, дельта) по снимкам, отсортированным по
    времени (чистая функция). None, если снимков меньше 2."""
    if len(snapshots) < 2:
        return None
    ordered = sorted(snapshots, key=lambda s: s[0])
    first = ordered[0][1]
    last = ordered[-1][1]
    return first, last, last - first


@dataclass(frozen=True)
class GrowthReport:
    """Результат расчёта отчёта о росте за период."""

    enough_data: bool
    snapshots_count: int
    min_required: int
    first_count: int | None = None
    last_count: int | None = None
    delta: int | None = None
    posts_by_style: dict[str, int] | None = None


def build_growth_report(window_days: int, min_snapshots: int) -> GrowthReport:
    """Собрать отчёт о росте: дельта подписчиков + посты по стилю за период."""
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    with session_scope() as session:
        snapshot_rows = (
            session.query(ChannelGrowthSnapshot.captured_at, ChannelGrowthSnapshot.subscriber_count)
            .filter(ChannelGrowthSnapshot.captured_at >= since)
            .all()
        )
        snapshots = [(captured_at, count) for captured_at, count in snapshot_rows]

        if len(snapshots) < min_snapshots:
            return GrowthReport(
                enough_data=False,
                snapshots_count=len(snapshots),
                min_required=min_snapshots,
            )

        styles = (
            session.query(Source.style_profile)
            .join(Post, Post.source_id == Source.id)
            .filter(
                Post.kind == PostKind.SOURCE,
                Post.status == PostStatus.POSTED,
                Post.posted_at >= since,
            )
            .all()
        )
        style_counts = Counter(s[0] or "default" for s in styles)

    delta_result = compute_growth_delta(snapshots)
    first, last, delta = delta_result if delta_result else (None, None, None)
    return GrowthReport(
        enough_data=True,
        snapshots_count=len(snapshots),
        min_required=min_snapshots,
        first_count=first,
        last_count=last,
        delta=delta,
        posts_by_style=dict(style_counts),
    )


def growth_summary() -> str:
    """Текст для команды бота `/growth`."""
    settings = get_settings()
    report = build_growth_report(settings.growth_report_window_days, settings.growth_min_snapshots)
    if not report.enough_data:
        return (
            f"📊 Недостаточно данных о росте: {report.snapshots_count} снимков, "
            f"нужно минимум {report.min_required}.\n"
            f"Включи GROWTH_TRACKING_ENABLED и подожди накопления."
        )
    lines = [
        f"📊 Рост за {settings.growth_report_window_days} дн.:",
        f"• Подписчиков было: {report.first_count}",
        f"• Подписчиков стало: {report.last_count}",
        f"• Изменение: {report.delta:+d}" if report.delta is not None else "• Изменение: н/д",
    ]
    if report.posts_by_style:
        styles = ", ".join(f"{k}: {v}" for k, v in sorted(report.posts_by_style.items()))
        lines.append(f"• Постов по стилям за период: {styles}")
    lines.append(
        "⚠️ Это счётчики, не статистическая корреляция — для выводов о "
        "причинности нужно намного больше данных."
    )
    return "\n".join(lines)
