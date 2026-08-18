"""Сбор статистики опубликованных постов (F14).

Периодически опрашивает просмотры/пересылки/реакции опубликованных постов
через Telethon (юзер-сессия видит метрики каналов) и пишет снимки в
`post_stats`. Команда бота `/stats` и веб-страница `/stats` (Фаза 5.3)
агрегируют данные за период через `compute_stats_summary` — структурированные
данные отдельно от текстового форматирования, как и в `smart_schedule.py`/
`growth.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from telethon import TelegramClient

from tg_repost import post_stats_repo, post_targets_repo
from tg_repost.antiban import HourlyRateLimiter, jitter_sleep
from tg_repost.config import get_settings
from tg_repost.db.models import Post, PostStat, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

# F25 — эмодзи, которые считаем негативной реакцией. Список короткий и
# консервативный (не пытается покрыть все возможные эмодзи-реакции Telegram) —
# ложноотрицательный пропуск здесь безопаснее ложноположительного авто-удаления.
_NEGATIVE_EMOJI = frozenset({"👎", "💩", "🤮", "😡", "🤬", "😢", "😭"})

# F25 — потолок авто-удалений в час (защита от скоординированного всплеска
# негативных реакций, см. config.py::max_auto_deletes_per_hour). Лениво
# создаётся при первом обращении, чтобы настройки уже были загружены —
# тот же паттерн, что `_rate_limiters` в telegram/listener.py.
_auto_delete_limiter: HourlyRateLimiter | None = None


def _get_auto_delete_limiter() -> HourlyRateLimiter:
    global _auto_delete_limiter
    if _auto_delete_limiter is None:
        _auto_delete_limiter = HourlyRateLimiter(get_settings().max_auto_deletes_per_hour)
    return _auto_delete_limiter


def _count_reactions(message) -> int | None:
    """Суммарное число реакций на сообщении Telethon (если есть)."""
    reactions = getattr(message, "reactions", None)
    if not reactions or not getattr(reactions, "results", None):
        return None
    return sum(getattr(r, "count", 0) for r in reactions.results)


def _count_negative_reactions(message) -> int:
    """Сколько реакций из `_NEGATIVE_EMOJI` набрал пост (F25).

    Кастомные эмодзи-реакции (`ReactionCustomEmoji`, без `.emoticon`) не
    учитываются — нет простого способа сопоставить произвольный custom-emoji
    document_id с «негативностью» без отдельного справочника.
    """
    reactions = getattr(message, "reactions", None)
    if not reactions or not getattr(reactions, "results", None):
        return 0
    total = 0
    for r in reactions.results:
        emoticon = getattr(getattr(r, "reaction", None), "emoticon", None)
        if emoticon in _NEGATIVE_EMOJI:
            total += getattr(r, "count", 0)
    return total


async def _handle_negative_reactions(
    bot: Bot | None,
    post_id: int,
    chat_id: int,
    message_id: int,
    negative_count: int,
) -> None:
    """Уведомить владельца и (опционально) удалить пост при превышении
    порога негативных реакций (F25). Идемпотентно — уведомляет один раз на
    пост (`Post.negative_alert_sent`), даже если порог остаётся превышенным
    на следующих циклах сбора статистики.

    ВАЖНО про порядок: `negative_alert_sent` выставляется ТОЛЬКО ПОСЛЕ
    успешной отправки уведомления, а не до неё. Раньше флаг ставился первым
    (до отправки) — если процесс падал или `send_message` бросал что-то
    между записью флага и реальной отправкой, владелец тихо никогда не
    узнавал о проблемном посте: флаг уже стоит, следующий цикл сбора
    статистики просто пропускает пост (`if post.negative_alert_sent: return`
    в начале). Теперь при неудачной отправке флаг НЕ ставится — следующий
    цикл сбора статистики (см. `collect_stats`) попробует уведомить снова
    (найдено при код-ревью Фазы 5+).
    """
    settings = get_settings()
    with session_scope() as session:
        post = session.get(Post, post_id)
        if post is None or post.negative_alert_sent:
            return

    if bot is None:
        logger.warning(
            "F25: порог негативных реакций превышен у поста %s (%d), но бот не "
            "запущен — уведомление не отправлено (повторим на следующем цикле)",
            post_id, negative_count,
        )
        return

    # Потолок авто-удалений в час — защита от скоординированного всплеска
    # негативных реакций (бригадинг), который иначе мог бы вызвать массовое
    # необратимое удаление легитимных постов за один цикл сбора статистики
    # (найдено при security-аудите Фазы 5+). Решаем ДО отправки уведомления,
    # чтобы текст сообщения владельцу был честным (не "удалён", если на
    # самом деле пропущено из-за лимита).
    will_delete = settings.auto_delete_on_negative and _get_auto_delete_limiter().try_acquire()

    text = f"⚠️ Пост #{post_id} набрал {negative_count} негативных реакций."
    if settings.auto_delete_on_negative:
        if will_delete:
            text += " Пост автоматически удалён."
        else:
            text += (
                " Авто-удаление ПРОПУЩЕНО (превышен часовой лимит "
                f"{settings.max_auto_deletes_per_hour} удалений) — реши вручную."
            )
    try:
        await bot.send_message(chat_id=settings.tg_owner_user_id, text=text)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "F25: не удалось отправить уведомление о посте %s: %s — "
            "попробуем снова на следующем цикле", post_id, exc,
        )
        return  # НЕ ставим negative_alert_sent — уведомление не доставлено

    with session_scope() as session:
        post = session.get(Post, post_id)
        if post is not None:
            post.negative_alert_sent = True
            if will_delete:
                post.status_reason = f"авто-удалён: {negative_count} негативных реакций"

    if will_delete:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
            logger.info(
                "F25: пост %s удалён из %s (%d негативных реакций)",
                post_id, chat_id, negative_count,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("F25: не удалось удалить пост %s: %s", post_id, exc)


async def collect_stats(client: TelegramClient, bot: Bot | None = None) -> int:
    """Снять метрики недавно опубликованных постов. Возвращает число снимков.

    F31: раньше опрашивалась только ПЕРВАЯ цель публикации (`Post.
    posted_chat_id`/`posted_message_id`) — если пост ушёл в несколько групп,
    метрики остальных целей нигде не учитывались. Теперь опрашиваются ВСЕ
    успешные цели (см. `post_targets_repo.py`, F29) и суммируются в один
    снимок `PostStat` на пост — просмотры/форварды/реакции физически
    привязаны к конкретному сообщению в конкретном чате, `PostStat` же
    остаётся ПОСТ-уровневым (не хочется плодить снимки на каждую цель —
    /stats и так агрегирует по постам, не по целям).

    `bot` нужен только для F25 (уведомление/авто-удаление при
    негативных реакциях) — без него сбор метрик работает как раньше, просто
    без этой проверки (см. `_handle_negative_reactions`). F25-проверка
    теперь идёт ПО КАЖДОЙ цели отдельно (превышение порога в одной группе не
    должно ни маскироваться, ни удваиваться метриками другой)."""
    settings = get_settings()
    since = datetime.now(timezone.utc) - timedelta(days=settings.stats_window_days)

    with session_scope() as session:
        post_ids = [
            p.id
            for p in session.query(Post.id)
            .filter(Post.status == PostStatus.POSTED, Post.posted_at >= since)
            .all()
        ]

    captured = 0
    for post_id in post_ids:
        targets = [
            t for t in post_targets_repo.list_targets_for_post(post_id)
            if t.ok and t.message_id is not None
        ]
        if not targets:
            continue

        total_views = 0
        total_forwards = 0
        total_reactions = 0
        got_any = False
        for target in targets:
            # Гарантировано фильтром `targets` выше — mypy не может вывести
            # это через атрибут объекта, полученного из списка.
            assert target.message_id is not None
            try:
                message = await client.get_messages(target.chat_id, ids=target.message_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Не удалось получить метрики поста %s в %s: %s",
                    post_id, target.chat_id, exc,
                )
                continue
            if message is None:
                continue
            got_any = True
            total_views += getattr(message, "views", None) or 0
            total_forwards += getattr(message, "forwards", None) or 0
            total_reactions += _count_reactions(message) or 0

            if settings.negative_reaction_threshold > 0:
                negative = _count_negative_reactions(message)
                if negative >= settings.negative_reaction_threshold:
                    await _handle_negative_reactions(
                        bot, post_id, target.chat_id, target.message_id, negative,
                    )

            # F17 — мягкий джиттер между запросами метрик.
            await jitter_sleep(0.3, 1.0)

        if not got_any:
            continue
        # Аудит: раньше `total_views or None` — если сумма по всем целям
        # РЕАЛЬНО была 0 (не пропуск, а честный ноль, частое дело у нового
        # поста/малотрафичного канала), в БД писался NULL, неотличимый от
        # "метрика не снята вообще". `compute_stats_summary` ниже пропускает
        # строки с `view_count is None` при подсчёте среднего — такие посты
        # молча выпадали из знаменателя, завышая среднее. `got_any=True`
        # здесь уже гарантирует, что хотя бы один get_messages реально
        # ответил — сумма настоящая, ноль в том числе.
        with session_scope() as session:
            session.add(
                PostStat(
                    post_id=post_id,
                    view_count=total_views,
                    forward_count=total_forwards,
                    reaction_count=total_reactions,
                )
            )
        captured += 1

    logger.info("Статистика собрана по %d постам", captured)
    return captured


@dataclass(frozen=True)
class StatsSummary:
    """Структурированная сводка статистики за период (для /stats и веб-страницы)."""

    window_days: int
    published: int
    counted: int
    total_views: int
    avg_views: float
    top_post_id: int | None
    top_post_views: int


def compute_stats_summary(window_days: int) -> StatsSummary:
    """Сводка по опубликованным постам за период (последний снимок на пост)."""
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    with session_scope() as session:
        posts = (
            session.query(Post)
            .filter(Post.status == PostStatus.POSTED, Post.posted_at >= since)
            .all()
        )
        if not posts:
            return StatsSummary(
                window_days=window_days, published=0, counted=0, total_views=0,
                avg_views=0.0, top_post_id=None, top_post_views=0,
            )

        # Один запрос на все посты вместо запроса на каждый: раньше здесь был
        # N+1, а отбор «последнего снимка» — своя копия, разошедшаяся с тремя
        # другими такими же (см. `post_stats_repo`).
        latest = post_stats_repo.latest_stats_for(session, [p.id for p in posts])

        total_views = 0
        counted = 0
        best: tuple[int, int | None] = (0, None)  # (views, post_id)
        for post in posts:
            last = latest.get(post.id)
            if last and last.view_count is not None:
                total_views += last.view_count
                counted += 1
                if last.view_count > best[0]:
                    best = (last.view_count, post.id)

        published = len(posts)
        avg = total_views / counted if counted else 0.0

    return StatsSummary(
        window_days=window_days, published=published, counted=counted,
        total_views=total_views, avg_views=avg,
        top_post_id=best[1], top_post_views=best[0],
    )


def stats_summary(window_days: int) -> str:
    """Текстовая сводка для команды бота /stats."""
    summary = compute_stats_summary(window_days)
    if summary.published == 0:
        return f"За последние {window_days} дн. опубликованных постов нет."

    lines = [
        f"📊 Статистика за {window_days} дн.:",
        f"• Опубликовано постов: {summary.published}",
        f"• С метриками просмотров: {summary.counted}",
        f"• Суммарно просмотров: {summary.total_views}",
        f"• В среднем на пост: {summary.avg_views:.0f}",
    ]
    if summary.top_post_id is not None:
        lines.append(f"• Топ-пост: #{summary.top_post_id} ({summary.top_post_views} просмотров)")

    engagement = engagement_lines(window_days)
    if engagement:
        lines.extend(["", *engagement])
    return "\n".join(lines)


def engagement_lines(window_days: int) -> list[str]:
    """Блок ERR/ER по каждому активному каналу (F53).

    Отдельной функцией, а не внутри `stats_summary`: те же строки нужны
    веб-странице, а дублировать формулировки в двух местах — верный способ
    получить два разных числа под одним названием.

    Каналы без данных пропускаются молча. Показывать «ERR: —» по каналу, где
    ещё нет ни одного замера, значит засорять сводку строками, из которых
    ничего не следует.
    """
    from tg_repost import engagement_repo, targets_repo

    out: list[str] = []
    for target in targets_repo.list_targets():
        if not target.is_active:
            continue
        report = engagement_repo.build_engagement_report(target.chat_id, window_days)
        if not report.enough_data:
            continue

        title = target.title or str(target.chat_id)
        out.append(f"📈 {title}:")
        if report.reach_rate is not None:
            out.append(
                f"  • ERR (охват к подписчикам): {report.reach_rate}% "
                f"— {report.avg_views} из {report.subscribers}"
            )
        else:
            # Причину называем прямо: без снимка подписчиков ERR не считается,
            # и это чинится включением growth-трекера, а не ожиданием.
            out.append("  • ERR: нет снимка подписчиков (F22)")
        if report.engagement_rate is not None:
            out.append(f"  • ER (реакции+репосты к охвату): {report.engagement_rate}%")
        if report.posts_with_stats < report.posts_total:
            out.append(
                f"  • ⚠️ метрики есть у {report.posts_with_stats} из "
                f"{report.posts_total} постов — средние по ним"
            )
        out.extend(_mute_lines(target.chat_id, window_days))
    return out


def _mute_lines(chat_id: int, window_days: int) -> list[str]:
    """Динамика включённых уведомлений (F56), если она собрана.

    Молчим, когда снимков меньше двух: одна точка — это не динамика, а по
    одному значению «60% включили уведомления» владелец всё равно ничего не
    решит. Тревога поднимается только на падении, потому что рост здесь —
    хорошая новость, а не повод для строки в сводке.
    """
    from tg_repost.scheduler.channel_stats import mute_trend

    trend = mute_trend(chat_id, window_days)
    if not trend.enough_data:
        return []

    line = (
        f"  • Уведомления включены у {trend.last_pct}% "
        f"(было {trend.first_pct}%, за {window_days} дн.)"
    )
    # `is_alarming` уже гарантирует непустую дельту, но связываем её явно:
    # иначе проверка живёт в одном месте, а разыменование в другом, и любая
    # правка условия молча ломает вторую половину.
    delta = trend.delta
    if trend.is_alarming and delta is not None:
        return [
            line,
            f"  • ⚠️ ТИХИЙ ОТТОК: доля упала на {abs(delta)} п.п. "
            f"Люди ещё подписаны, но отключили звук — отписка обычно следом",
        ]
    return [line]
