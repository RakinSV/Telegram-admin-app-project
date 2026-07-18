"""Тесты F35 — ручной учёт рекламного дохода: `ads/revenue_repo.py`."""

from __future__ import annotations

from datetime import datetime, timezone

from tg_repost.ads import repo as ads_repo
from tg_repost.ads import revenue_repo
from tg_repost.db.models import AdBrief, AdRevenue
from tg_repost.db.session import session_scope


def _clean() -> None:
    with session_scope() as session:
        session.query(AdRevenue).delete()
        session.query(AdBrief).delete()


def test_add_revenue_creates_row():
    _clean()
    row = revenue_repo.add_revenue(
        "Telega.in", 1500.0, "RUB", datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    assert row.id is not None
    assert row.source == "Telega.in"
    assert row.amount == 1500.0
    assert row.currency == "RUB"
    assert row.ad_brief_id is None
    _clean()


def test_add_revenue_links_to_brief():
    _clean()
    brief = ads_repo.add_brief("test brief")
    row = revenue_repo.add_revenue(
        "Direct deal", 500.0, "USD", datetime(2026, 7, 1, tzinfo=timezone.utc),
        ad_brief_id=brief.id, note="one-off",
    )
    assert row.ad_brief_id == brief.id
    assert row.note == "one-off"
    _clean()


def test_list_revenue_ordered_newest_first():
    _clean()
    revenue_repo.add_revenue("A", 100, "RUB", datetime(2026, 1, 1, tzinfo=timezone.utc))
    revenue_repo.add_revenue("B", 200, "RUB", datetime(2026, 6, 1, tzinfo=timezone.utc))
    rows = revenue_repo.list_revenue()
    assert [r.source for r in rows] == ["B", "A"]
    _clean()


def test_delete_revenue_removes_row():
    _clean()
    row = revenue_repo.add_revenue("A", 100, "RUB", datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert revenue_repo.delete_revenue(row.id) is True
    assert revenue_repo.list_revenue() == []
    _clean()


def test_delete_revenue_missing_returns_false():
    assert revenue_repo.delete_revenue(999999) is False


def test_total_by_currency_sums_per_currency_not_mixed():
    _clean()
    revenue_repo.add_revenue("A", 100.0, "RUB", datetime(2026, 1, 1, tzinfo=timezone.utc))
    revenue_repo.add_revenue("B", 50.0, "RUB", datetime(2026, 2, 1, tzinfo=timezone.utc))
    revenue_repo.add_revenue("C", 30.0, "USD", datetime(2026, 3, 1, tzinfo=timezone.utc))
    totals = revenue_repo.total_by_currency()
    assert totals == {"RUB": 150.0, "USD": 30.0}
    _clean()


def test_total_by_currency_empty_when_no_revenue():
    _clean()
    assert revenue_repo.total_by_currency() == {}
