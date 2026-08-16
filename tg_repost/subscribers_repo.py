"""Кому бот может написать (F64).

Telegram не даёт боту заговорить первым: личная переписка открывается,
только когда человек сам нажал «Запустить» или пришёл по deep-link. Этот
модуль отвечает на вопрос «кому из сегмента мы физически можем отправить».

ТРИ ПРИЧИНЫ НЕ ПИСАТЬ ЧЕЛОВЕКУ, И ОНИ РАЗНЫЕ:

1. **не запускал бота** — его просто нет в этой таблице. Не ошибка, а
   обычное состояние большинства участников группы;
2. **заблокировал бота** (`is_blocked`) — решение Telegram. Пробовать снова
   бессмысленно, пока он сам не разблокирует, поэтому флаг снимается только
   его же сообщением;
3. **отписался кнопкой** (`unsubscribed_at`) — его собственное решение.
   Смешивать со вторым нельзя: отписавшийся продолжает получать ответы на
   свои вопросы, он отказался только от рассылок.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from tg_repost.db.models import BotSubscriber
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def record_contact(
    user_id: int, *, username: str | None = None, first_name: str | None = None
) -> bool:
    """Человек написал боту — значит писать ему можно. `True` — он новый.

    Зовётся на каждое личное сообщение, а не только на `/start`: человек мог
    начать общение с ботом до появления этой таблицы, и единственный способ
    о нём узнать — заметить его сообщение.

    ЛЮБОЕ сообщение снимает `is_blocked`: раз оно дошло, блокировки больше
    нет. А вот отписку от рассылок НЕ снимает — от неё человек отказался
    сознательно, и «написал боту» не значит «передумал».
    """
    with session_scope() as session:
        row = (
            session.query(BotSubscriber)
            .filter(BotSubscriber.user_id == user_id)
            .first()
        )
        if row is None:
            session.add(
                BotSubscriber(
                    user_id=user_id, username=username, first_name=first_name,
                )
            )
            return True

        row.last_seen_at = _utcnow()
        row.is_blocked = False
        if username is not None:
            row.username = username
        if first_name is not None:
            row.first_name = first_name
        return False


def mark_blocked(user_id: int) -> None:
    """Telegram сказал, что бот заблокирован. Больше не пробуем."""
    with session_scope() as session:
        row = (
            session.query(BotSubscriber)
            .filter(BotSubscriber.user_id == user_id)
            .first()
        )
        if row is not None:
            row.is_blocked = True
            row.last_seen_at = _utcnow()


def unsubscribe(user_id: int) -> bool:
    """Человек отказался от рассылок. `False` — он уже был отписан."""
    with session_scope() as session:
        row = (
            session.query(BotSubscriber)
            .filter(BotSubscriber.user_id == user_id)
            .first()
        )
        if row is None or row.unsubscribed_at is not None:
            return False
        row.unsubscribed_at = _utcnow()
        return True


def resubscribe(user_id: int) -> bool:
    with session_scope() as session:
        row = (
            session.query(BotSubscriber)
            .filter(BotSubscriber.user_id == user_id)
            .first()
        )
        if row is None or row.unsubscribed_at is None:
            return False
        row.unsubscribed_at = None
        return True


def is_reachable(user_id: int) -> bool:
    with session_scope() as session:
        row = (
            session.query(BotSubscriber)
            .filter(
                BotSubscriber.user_id == user_id,
                BotSubscriber.is_blocked.is_(False),
                BotSubscriber.unsubscribed_at.is_(None),
            )
            .first()
        )
        return row is not None


def reachable_among(user_ids: list[int], *, after_user_id: int | None = None) -> list[int]:
    """Кому из списка можно написать, по возрастанию id.

    `after_user_id` — для продолжения прерванной рассылки: берём только тех,
    кто идёт ПОСЛЕ последнего отправленного. Отсюда и сортировка по id:
    порядок стабилен между запусками, поэтому после обрыва никто не получит
    сообщение дважды и никто не будет пропущен.
    """
    if not user_ids:
        return []
    with session_scope() as session:
        query = session.query(BotSubscriber.user_id).filter(
            BotSubscriber.user_id.in_(user_ids),
            BotSubscriber.is_blocked.is_(False),
            BotSubscriber.unsubscribed_at.is_(None),
        )
        if after_user_id is not None:
            query = query.filter(BotSubscriber.user_id > after_user_id)
        rows = query.order_by(BotSubscriber.user_id.asc()).all()
        return [row[0] for row in rows]


@dataclass(frozen=True)
class ReachStats:
    """Сколько человек в выборке и скольким реально можно написать.

    Две цифры, а не одна: разрыв между ними и есть та правда о рассылке,
    которую владелец обязан видеть ДО отправки.
    """

    total: int
    reachable: int
    never_started: int
    blocked: int
    unsubscribed: int


def all_user_ids() -> list[int]:
    """Все, кто когда-либо запускал бота.

    Нужен, чтобы посчитать охват целиком (F73), не дублируя разбор на
    категории: он живёт в `reach_stats` и должен остаться в одном месте —
    «не запускал», «заблокировал» и «отписался» уже один раз путали.
    """
    with session_scope() as session:
        return [row.user_id for row in session.query(BotSubscriber.user_id).all()]


def reach_stats(user_ids: list[int]) -> ReachStats:
    """Разложить выборку по причинам недостижимости."""
    if not user_ids:
        return ReachStats(0, 0, 0, 0, 0)

    with session_scope() as session:
        rows = (
            session.query(
                BotSubscriber.user_id,
                BotSubscriber.is_blocked,
                BotSubscriber.unsubscribed_at,
            )
            .filter(BotSubscriber.user_id.in_(user_ids))
            .all()
        )

    known = {row[0]: (row[1], row[2]) for row in rows}
    blocked = sum(1 for uid in user_ids if known.get(uid, (False, None))[0])
    unsubscribed = sum(
        1
        for uid in user_ids
        if uid in known and known[uid][1] is not None and not known[uid][0]
    )
    never = sum(1 for uid in user_ids if uid not in known)
    return ReachStats(
        total=len(user_ids),
        reachable=len(user_ids) - blocked - unsubscribed - never,
        never_started=never,
        blocked=blocked,
        unsubscribed=unsubscribed,
    )
