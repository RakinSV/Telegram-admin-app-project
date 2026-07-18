"""Ручной учёт рекламного дохода (F35) — журнал, не интеграция с биржей
(см. `AdRevenue` docstring в `db/models.py`). Переиспользуется веб-админкой
(`webui/crud_routes.py`, роуты `/ads/revenue`)."""

from __future__ import annotations

from datetime import datetime

from tg_repost.db.models import AdRevenue
from tg_repost.db.session import session_scope


def add_revenue(
    source: str,
    amount: float,
    currency: str,
    recorded_at: datetime,
    ad_brief_id: int | None = None,
    note: str | None = None,
) -> AdRevenue:
    with session_scope() as session:
        row = AdRevenue(
            ad_brief_id=ad_brief_id, source=source, amount=amount,
            currency=currency, recorded_at=recorded_at, note=note,
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        return row


def list_revenue(limit: int = 500) -> list[AdRevenue]:
    with session_scope() as session:
        return (
            session.query(AdRevenue)
            .order_by(AdRevenue.recorded_at.desc())
            .limit(limit)
            .all()
        )


def delete_revenue(revenue_id: int) -> bool:
    with session_scope() as session:
        deleted = session.query(AdRevenue).filter(AdRevenue.id == revenue_id).delete()
        return deleted > 0


def total_by_currency(rows: list[AdRevenue] | None = None) -> dict[str, float]:
    """Сумма дохода по каждой валюте — валюты не конвертируются друг в
    друга (нет источника курсов), поэтому итог всегда разбит по ним,
    никогда не смешивается в одно число."""
    if rows is None:
        rows = list_revenue()
    totals: dict[str, float] = {}
    for row in rows:
        totals[row.currency] = totals.get(row.currency, 0.0) + row.amount
    return totals
