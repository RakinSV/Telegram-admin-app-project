"""Статистика — `/stats` (G11) и `/growth` (G17).

`_require_admin` переиспользуется из `handlers/admin.py` (та же проверка
прав, тот же TTL-кэш админов) — намеренно, не дублируется здесь."""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from guardian.db.models import DailyStats
from guardian.handlers.admin import _require_admin
from guardian.services import daily_stats_repo

router = Router(name="stats")

_PERIODS = {"день": 1, "неделя": 7, "месяц": 30}
_SPARKLINE_CHARS = "▁▂▃▄▅▆▇█"


def _parse_period(arg: str) -> tuple[str, int]:
    arg = arg.strip().lower()
    if arg in _PERIODS:
        return arg, _PERIODS[arg]
    return "неделя", 7


def format_stats_text(period_label: str, totals: dict[str, float], top_words: list[tuple[str, int]]) -> str:
    lines = [f"📊 Модерация за {period_label}:"]
    lines.append(f"• Удалено сообщений: {int(totals['deleted_msgs'])}")
    lines.append(f"• Выдано варнов: {int(totals['warnings'])}")
    lines.append(
        f"• Мутов: {int(totals['mutes'])}, Банов: {int(totals['bans'])}, Киков: {int(totals['kicks'])}"
    )
    new_members = int(totals["new_members"])
    if new_members > 0:
        verified = int(totals["verified_members"])
        pct = round(verified / new_members * 100)
        lines.append(f"• Прошли верификацию: {verified}/{new_members} ({pct}%)")
    if top_words:
        words_str = ", ".join(f"«{word}» x{count}" for word, count in top_words)
        lines.append(f"• Стоп-слова: {words_str}")
    ai_calls = int(totals["ai_calls"])
    if ai_calls > 0:
        lines.append(f"• AI-вызовов: {ai_calls}, стоимость: ~${totals['ai_cost_usd']:.2f}")
    return "\n".join(lines)


def _sparkline(values: list[int]) -> str:
    if not values:
        return ""
    peak = max(values) or 1
    scale = len(_SPARKLINE_CHARS) - 1
    return "".join(_SPARKLINE_CHARS[min(int(v / peak * scale), scale)] for v in values)


def format_growth_text(period_label: str, rows: list[DailyStats]) -> str:
    new_members = [r.new_members for r in rows]
    total_new = sum(new_members)
    total_verified = sum(r.verified_members for r in rows)
    spark = _sparkline(new_members)
    conversion_pct = round(total_verified / total_new * 100) if total_new else 0
    lines = [f"📈 Прирост участников за {period_label}:"]
    if spark:
        lines.append(spark)
    lines.append(f"Новых: {total_new}, прошли верификацию: {total_verified}/{total_new} ({conversion_pct}%)")
    return "\n".join(lines)


@router.message(Command("stats"))
async def cmd_stats(message: Message, command: CommandObject, bot: Bot) -> None:
    if await _require_admin(message, bot) is None:
        return
    period_label, days = _parse_period(command.args or "")
    chat_id = message.chat.id
    totals = daily_stats_repo.sum_range(chat_id, days)
    top_words = daily_stats_repo.top_stop_words(chat_id, days)
    await message.reply(format_stats_text(period_label, totals, top_words))


@router.message(Command("growth"))
async def cmd_growth(message: Message, command: CommandObject, bot: Bot) -> None:
    if await _require_admin(message, bot) is None:
        return
    period_label, days = _parse_period(command.args or "неделя")
    chat_id = message.chat.id
    daily_stats_repo.compute_and_store_daily_stats(chat_id)  # свежие данные за сегодня
    rows = daily_stats_repo.daily_stats_range(chat_id, days)
    await message.reply(format_growth_text(period_label, rows))
