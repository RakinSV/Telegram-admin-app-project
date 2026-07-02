"""Агрегация суточной статистики (G11/G17) — таблица `daily_stats`.

Два пути записи:
- `record_ai_call()` — инкремент СРАЗУ, при каждом AI-вызове
  (`filters/ai_filter.py::classify`) — не батчится, точнее и переживает
  рестарт процесса (в отличие от накопления в памяти).
- `compute_and_store_daily_stats()` — ПЕРЕСЧИТЫВАЕТ (не инкрементально)
  остальные счётчики из `moderation_log`/`members` за календарный день,
  вызывается ежедневной APScheduler-джобой (`bot.py`) — дешевле и надёжнее
  пересчитать заново из источника истины, чем поддерживать инкрементальные
  счётчики и рисковать их рассинхроном с `moderation_log`.
"""

from __future__ import annotations

from collections import Counter
from datetime import date as date_type
from datetime import datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from guardian.db.models import DailyStats, Member, ModerationLog
from guardian.db.session import session_scope


def _day_bounds(day: date_type) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def _get_or_create(session: Session, day: date_type, chat_id: int) -> DailyStats:
    row = (
        session.query(DailyStats)
        .filter(DailyStats.date == day, DailyStats.chat_id == chat_id)
        .one_or_none()
    )
    if row is None:
        row = DailyStats(date=day, chat_id=chat_id)
        session.add(row)
        session.flush()
    return row


def record_ai_call(chat_id: int, cost_usd: float, day: date_type | None = None) -> None:
    day = day or datetime.now(timezone.utc).date()
    with session_scope() as session:
        row = _get_or_create(session, day, chat_id)
        row.ai_calls += 1
        row.ai_cost_usd += cost_usd


def compute_and_store_daily_stats(chat_id: int, day: date_type | None = None) -> DailyStats:
    """Пересчитать счётчики модерации/участников за `day` (по умолчанию —
    сегодня, UTC). `ai_calls`/`ai_cost_usd` не трогает — те пишет
    `record_ai_call()` отдельно, в реальном времени."""
    day = day or datetime.now(timezone.utc).date()
    start, end = _day_bounds(day)
    with session_scope() as session:
        logs = (
            session.query(ModerationLog)
            .filter(
                ModerationLog.chat_id == chat_id,
                ModerationLog.created_at >= start,
                ModerationLog.created_at < end,
            )
            .all()
        )
        counts = Counter(log.action for log in logs)

        new_members = (
            session.query(Member)
            .filter(Member.chat_id == chat_id, Member.join_date >= start, Member.join_date < end)
            .count()
        )
        verified_members = (
            session.query(Member)
            .filter(
                Member.chat_id == chat_id,
                Member.join_date >= start,
                Member.join_date < end,
                Member.is_verified.is_(True),
            )
            .count()
        )

        row = _get_or_create(session, day, chat_id)
        row.deleted_msgs = counts.get("delete_msg", 0)
        row.warnings = counts.get("warn", 0)
        row.mutes = counts.get("mute", 0)
        row.kicks = counts.get("kick", 0)
        row.bans = counts.get("ban", 0)
        row.new_members = new_members
        row.verified_members = verified_members
        session.flush()
        session.refresh(row)
        return row


def daily_stats_range(chat_id: int, days: int) -> list[DailyStats]:
    """Последние `days` дней (включая сегодня), по возрастанию даты —
    используется `/growth` для спарклайна (G17)."""
    today = datetime.now(timezone.utc).date()
    since = today - timedelta(days=days - 1)
    with session_scope() as session:
        return (
            session.query(DailyStats)
            .filter(DailyStats.chat_id == chat_id, DailyStats.date >= since)
            .order_by(DailyStats.date.asc())
            .all()
        )


_SUM_FIELDS = (
    "deleted_msgs", "warnings", "mutes", "kicks", "bans", "new_members", "verified_members", "ai_calls",
)


def sum_range(chat_id: int, days: int) -> dict[str, float]:
    """Суммарные счётчики за период — для `/stats` (G11). Пересчитывает
    СЕГОДНЯШНЮЮ запись перед суммированием (не ждёт ежедневную джобу) —
    иначе `/stats день` показывал бы 0 до того, как джоба впервые
    сработает по расписанию."""
    compute_and_store_daily_stats(chat_id)
    rows = daily_stats_range(chat_id, days)
    totals: dict[str, float] = {field: sum(getattr(r, field) for r in rows) for field in _SUM_FIELDS}
    totals["ai_cost_usd"] = sum(r.ai_cost_usd for r in rows)
    return totals


def top_stop_words(chat_id: int, days: int, limit: int = 5) -> list[tuple[str, int]]:
    """Самые частые сработавшие стоп-слова за период — парсит `reason` записей
    `delete_msg` вида "стоп-слово: X" (см. `handlers/messages.py`), отдельная
    таблица под это заводиться не стала — сработавшее слово и так есть в
    `moderation_log`, дублировать некуда."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with session_scope() as session:
        logs = (
            session.query(ModerationLog)
            .filter(
                ModerationLog.chat_id == chat_id,
                ModerationLog.action == "delete_msg",
                ModerationLog.reason.like("стоп-слово: %"),
                ModerationLog.created_at >= since,
            )
            .all()
        )
    counter = Counter(log.reason.removeprefix("стоп-слово: ") for log in logs if log.reason)
    return counter.most_common(limit)
