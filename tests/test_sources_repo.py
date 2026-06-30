"""Тесты CRUD-логики источников (F01, F12, F15, F16, Фаза 5.3)."""

import pytest

from tg_repost import sources_repo
from tg_repost.db.models import Source
from tg_repost.db.session import session_scope


def _clear_sources() -> None:
    with session_scope() as session:
        session.query(Source).delete()


def test_normalize_username_strips_at_and_url():
    assert sources_repo.normalize_username("@durov") == "durov"
    assert sources_repo.normalize_username("https://t.me/durov") == "durov"
    assert sources_repo.normalize_username("t.me/durov") == "durov"
    assert sources_repo.normalize_username("durov") == "durov"


def test_add_source_creates_new():
    _clear_sources()
    source, created = sources_repo.add_source("@testchan")
    assert created is True
    assert source.channel_username == "testchan"
    assert source.is_active is True


def test_add_source_reactivates_existing():
    _clear_sources()
    source, _ = sources_repo.add_source("@testchan")
    sources_repo.deactivate_source(source.id)

    again, created = sources_repo.add_source("@testchan")
    assert created is False
    assert again.id == source.id
    assert again.is_active is True


def test_list_sources_ordered_by_id():
    _clear_sources()
    sources_repo.add_source("@chan_a")
    sources_repo.add_source("@chan_b")
    sources = sources_repo.list_sources()
    assert [s.channel_username for s in sources] == ["chan_a", "chan_b"]


def test_get_source_returns_none_for_missing():
    _clear_sources()
    assert sources_repo.get_source(999999) is None


def test_find_source_by_username():
    _clear_sources()
    source, _ = sources_repo.add_source("@findme")
    found = sources_repo.find_source_by_username("findme")
    assert found is not None
    assert found.id == source.id
    assert sources_repo.find_source_by_username("missing") is None


def test_deactivate_source():
    _clear_sources()
    source, _ = sources_repo.add_source("@deact")
    assert sources_repo.deactivate_source(source.id) is True
    assert sources_repo.get_source(source.id).is_active is False
    assert sources_repo.deactivate_source(999999) is False


def test_set_source_style():
    _clear_sources()
    source, _ = sources_repo.add_source("@styled")
    assert sources_repo.set_source_style(source.id, "news") is True
    assert sources_repo.get_source(source.id).style_profile == "news"
    assert sources_repo.set_source_style(999999, "news") is False


def test_set_source_enrich_modes():
    _clear_sources()
    source, _ = sources_repo.add_source("@enrich")
    sources_repo.set_source_enrich(source.id, "on")
    assert sources_repo.get_source(source.id).enrich_sources is True
    sources_repo.set_source_enrich(source.id, "off")
    assert sources_repo.get_source(source.id).enrich_sources is False
    sources_repo.set_source_enrich(source.id, "default")
    assert sources_repo.get_source(source.id).enrich_sources is None


def test_set_source_enrich_invalid_mode_raises():
    _clear_sources()
    source, _ = sources_repo.add_source("@badmode")
    with pytest.raises(ValueError):
        sources_repo.set_source_enrich(source.id, "bogus")


def test_set_source_targets_csv():
    _clear_sources()
    source, _ = sources_repo.add_source("@targeted")
    assert sources_repo.set_source_targets(source.id, "-100123, -100456") is True
    assert sources_repo.get_source(source.id).target_chat_ids == "-100123,-100456"


def test_set_source_targets_clear():
    _clear_sources()
    source, _ = sources_repo.add_source("@cleared")
    sources_repo.set_source_targets(source.id, "-100123")
    sources_repo.set_source_targets(source.id, None)
    assert sources_repo.get_source(source.id).target_chat_ids is None


def test_set_source_targets_invalid_csv_raises():
    _clear_sources()
    source, _ = sources_repo.add_source("@invalidtargets")
    with pytest.raises(ValueError):
        sources_repo.set_source_targets(source.id, "not-a-number")
