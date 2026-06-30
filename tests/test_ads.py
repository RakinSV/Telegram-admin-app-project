"""Тесты нативной рекламы (F21): периодичность и выбор брифа."""

from tg_repost.ads.injector import ads_due, select_next_ad_brief
from tg_repost.db.models import AdBrief
from tg_repost.db.session import session_scope


def test_ads_due_disabled_when_every_nth_zero():
    assert ads_due(100, 0, 0) is False
    assert ads_due(100, 0, -1) is False


def test_ads_due_first_trigger_at_nth_post():
    assert ads_due(4, 0, 5) is False
    assert ads_due(5, 0, 5) is True


def test_ads_due_does_not_retrigger_in_same_window():
    assert ads_due(9, 1, 5) is False


def test_ads_due_triggers_next_window():
    assert ads_due(10, 1, 5) is True


def _clear_ad_briefs() -> None:
    """Деактивировать все существующие брифы для изоляции теста."""
    with session_scope() as session:
        session.query(AdBrief).update({"is_active": False})


def test_select_next_ad_brief_picks_lowest_times_used():
    _clear_ad_briefs()
    with session_scope() as session:
        low = AdBrief(brief_text="low-usage-brief", is_active=True, times_used=0)
        high = AdBrief(brief_text="high-usage-brief", is_active=True, times_used=10)
        session.add_all([low, high])
        session.flush()
        low_id = low.id

    with session_scope() as session:
        picked = select_next_ad_brief(session)
        assert picked is not None
        assert picked.id == low_id


def test_select_next_ad_brief_skips_exhausted():
    _clear_ad_briefs()
    with session_scope() as session:
        exhausted = AdBrief(brief_text="exhausted", is_active=True, times_used=3, max_uses=3)
        available = AdBrief(brief_text="available", is_active=True, times_used=1, max_uses=5)
        session.add_all([exhausted, available])
        session.flush()
        available_id = available.id

    with session_scope() as session:
        picked = select_next_ad_brief(session)
        assert picked is not None
        assert picked.id == available_id


def test_select_next_ad_brief_none_when_no_active():
    _clear_ad_briefs()
    with session_scope() as session:
        assert select_next_ad_brief(session) is None
