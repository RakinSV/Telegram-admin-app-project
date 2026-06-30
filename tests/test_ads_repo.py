"""Тесты CRUD-логики брифов рекламы (F21, Фаза 5.3) — отдельно от
test_ads.py (тот покрывает ads_due/select_next_ad_brief из injector.py)."""

from tg_repost.ads import repo as ads_repo
from tg_repost.db.models import AdBrief
from tg_repost.db.session import session_scope


def _clear_briefs() -> None:
    with session_scope() as session:
        session.query(AdBrief).delete()


def test_add_brief_creates_with_defaults():
    _clear_briefs()
    brief = ads_repo.add_brief("buy our product", max_uses=5)
    assert brief.brief_text == "buy our product"
    assert brief.max_uses == 5
    assert brief.is_active is True
    assert brief.times_used == 0


def test_add_brief_unlimited_uses():
    _clear_briefs()
    brief = ads_repo.add_brief("forever ad", max_uses=None)
    assert brief.max_uses is None


def test_list_briefs_ordered_by_id():
    _clear_briefs()
    ads_repo.add_brief("first")
    ads_repo.add_brief("second")
    briefs = ads_repo.list_briefs()
    assert [b.brief_text for b in briefs] == ["first", "second"]


def test_get_brief_returns_none_for_missing():
    _clear_briefs()
    assert ads_repo.get_brief(999999) is None


def test_disable_brief():
    _clear_briefs()
    brief = ads_repo.add_brief("to disable")
    assert ads_repo.disable_brief(brief.id) is True
    assert ads_repo.get_brief(brief.id).is_active is False
    assert ads_repo.disable_brief(999999) is False
