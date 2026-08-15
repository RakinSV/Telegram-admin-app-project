"""Заявки рекламодателей и бронь мест в сетке (F66).

Замыкает цепочку, которая до сих пор рвалась: бриф (F21) — это уже принятая
задача для ИИ, журнал дохода (F35) — уже полученные деньги, а между ними
зияла переписка в личке. Теперь заявка живёт в системе от прихода до денег.

ДВОЙНАЯ ПРОДАЖА МЕСТА — то, ради чего здесь вообще есть логика, а не просто
CRUD. Две принятые заявки на одну дату в одном канале означают, что владелец
пообещал одно и то же двоим, и узнает об этом кто-то из них — уже после
оплаты. Проверка живёт здесь, а не в ограничении базы, потому что человеку
надо СКАЗАТЬ, с кем конфликт, а не показать ошибку уникальности.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from tg_repost.db.models import AdBrief, AdRequest, AdRevenue
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

STATUS_NEW = "new"
STATUS_ACCEPTED = "accepted"
STATUS_DECLINED = "declined"
STATUS_PUBLISHED = "published"

# Статусы, которые ЗАНИМАЮТ дату. Отклонённая заявка место не держит —
# иначе один отказ блокировал бы день навсегда.
_OCCUPYING = (STATUS_ACCEPTED, STATUS_PUBLISHED)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SlotTaken(Exception):
    """Дата уже занята другой принятой заявкой.

    Несёт саму заявку-конфликт, а не только факт: владельцу нужно решить,
    кому отказать, а для этого надо видеть, кто там стоит.
    """

    def __init__(self, existing: "AdRequestView") -> None:
        super().__init__(
            f"Дата {existing.slot_date} уже занята заявкой #{existing.id} "
            f"({existing.advertiser})"
        )
        self.existing = existing


@dataclass(frozen=True)
class AdRequestView:
    id: int
    chat_id: int
    advertiser: str
    brief_text: str
    price: float | None
    currency: str
    slot_date: date
    status: str
    ad_brief_id: int | None
    ad_revenue_id: int | None
    note: str | None
    created_at: datetime
    decided_at: datetime | None


def _view(row: AdRequest) -> AdRequestView:
    return AdRequestView(
        id=row.id,
        chat_id=row.chat_id,
        advertiser=row.advertiser,
        brief_text=row.brief_text,
        price=row.price,
        currency=row.currency,
        slot_date=row.slot_date,
        status=row.status,
        ad_brief_id=row.ad_brief_id,
        ad_revenue_id=row.ad_revenue_id,
        note=row.note,
        created_at=row.created_at,
        decided_at=row.decided_at,
    )


def create(
    *,
    chat_id: int,
    advertiser: str,
    brief_text: str,
    slot_date: date,
    price: float | None = None,
    currency: str = "RUB",
    note: str | None = None,
) -> int | None:
    """Завести заявку. `None` — не заполнено обязательное.

    Конфликт дат здесь НЕ проверяется намеренно: заявка — это просьба, а не
    бронь. Пусть придут три заявки на одну дату, владелец выберет одну;
    отвергать входящие за него — значит терять деньги на ровном месте.
    """
    who = advertiser.strip()
    brief = brief_text.strip()
    if not who or not brief:
        return None

    with session_scope() as session:
        row = AdRequest(
            chat_id=chat_id,
            advertiser=who,
            brief_text=brief,
            price=price,
            currency=currency,
            slot_date=slot_date,
            note=(note or "").strip() or None,
            status=STATUS_NEW,
        )
        session.add(row)
        session.flush()
        logger.info(
            "F66: заявка #%d от «%s» на %s", row.id, who, slot_date,
        )
        return row.id


def get(request_id: int) -> AdRequestView | None:
    with session_scope() as session:
        row = session.get(AdRequest, request_id)
        return _view(row) if row else None


def list_all(chat_id: int | None = None, status: str | None = None) -> list[AdRequestView]:
    with session_scope() as session:
        query = session.query(AdRequest)
        if chat_id is not None:
            query = query.filter(AdRequest.chat_id == chat_id)
        if status is not None:
            query = query.filter(AdRequest.status == status)
        rows = query.order_by(AdRequest.slot_date.asc(), AdRequest.id.asc()).all()
        return [_view(row) for row in rows]


def occupied_dates(chat_id: int) -> dict[date, AdRequestView]:
    """Календарь занятости: какая дата какой заявкой занята.

    Только принятые и опубликованные. Отклонённая заявка место не держит —
    иначе один отказ блокировал бы день навсегда.
    """
    with session_scope() as session:
        rows = (
            session.query(AdRequest)
            .filter(AdRequest.chat_id == chat_id, AdRequest.status.in_(_OCCUPYING))
            .order_by(AdRequest.slot_date.asc())
            .all()
        )
        return {row.slot_date: _view(row) for row in rows}


def accept(request_id: int) -> int | None:
    """Принять заявку: создаёт бриф для ИИ. Возвращает id брифа.

    Бросает `SlotTaken`, если дата уже занята: продать одно место дважды —
    ошибка, которую нельзя исправить извинением.
    """
    with session_scope() as session:
        row = session.get(AdRequest, request_id)
        if row is None or row.status != STATUS_NEW:
            return None

        clash = (
            session.query(AdRequest)
            .filter(
                AdRequest.chat_id == row.chat_id,
                AdRequest.slot_date == row.slot_date,
                AdRequest.status.in_(_OCCUPYING),
                AdRequest.id != row.id,
            )
            .first()
        )
        if clash is not None:
            raise SlotTaken(_view(clash))

        # Бриф создаётся с лимитом в одно использование: заявка оплачена за
        # ОДНО размещение, и бриф, который ИИ возьмёт повторно, — это
        # бесплатная реклама за наш счёт.
        brief = AdBrief(brief_text=row.brief_text, max_uses=1)
        session.add(brief)
        session.flush()

        row.status = STATUS_ACCEPTED
        row.ad_brief_id = brief.id
        row.decided_at = _utcnow()
        logger.info(
            "F66: заявка #%d принята, создан бриф #%d на %s",
            row.id, brief.id, row.slot_date,
        )
        return brief.id


def decline(request_id: int, note: str | None = None) -> bool:
    with session_scope() as session:
        row = session.get(AdRequest, request_id)
        if row is None or row.status != STATUS_NEW:
            return False
        row.status = STATUS_DECLINED
        row.decided_at = _utcnow()
        if note:
            row.note = note.strip() or row.note
        return True


def mark_published(request_id: int, *, amount: float | None = None) -> int | None:
    """Отметить размещение состоявшимся: пишет доход. Возвращает id записи.

    Сумма берётся из заявки, если не передана явно — но передать можно:
    договорились на одну цену, получили другую, и врать журналу незачем.
    """
    with session_scope() as session:
        row = session.get(AdRequest, request_id)
        if row is None or row.status != STATUS_ACCEPTED:
            return None

        value = amount if amount is not None else row.price
        if value is None:
            # Без суммы записывать доход нечем. Статус всё равно двигаем:
            # размещение состоялось, а деньги владелец внесёт руками в F35.
            row.status = STATUS_PUBLISHED
            row.decided_at = _utcnow()
            logger.info("F66: заявка #%d опубликована без суммы", row.id)
            return None

        revenue = AdRevenue(
            ad_brief_id=row.ad_brief_id,
            source=row.advertiser,
            amount=value,
            currency=row.currency,
            recorded_at=_utcnow(),
            note=f"Заявка #{row.id}",
        )
        session.add(revenue)
        session.flush()

        row.status = STATUS_PUBLISHED
        row.ad_revenue_id = revenue.id
        row.decided_at = _utcnow()
        logger.info(
            "F66: заявка #%d опубликована, доход #%d на %s %s",
            row.id, revenue.id, value, row.currency,
        )
        return revenue.id


def delete(request_id: int) -> bool:
    """Удалить заявку. Уже опубликованную не трогаем: за ней стоит доход."""
    with session_scope() as session:
        row = session.get(AdRequest, request_id)
        if row is None or row.status == STATUS_PUBLISHED:
            return False
        session.delete(row)
        return True
