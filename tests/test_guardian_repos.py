"""Тесты общих repo-модулей Guardian (stopwords/domains/trusted) — общий
слой между Telegram-командами (`handlers/admin.py`) и веб-админкой tg_repost
(`tg_repost/webui/guardian_routes.py`)."""

from __future__ import annotations

import pytest

from guardian import domains_repo, stopwords_repo, trusted_repo
from guardian.db.models import BotConfig, Member, ModerationLog, StopWord, TrustedUser
from guardian.db.session import session_scope


@pytest.fixture(autouse=True)
def _clear_tables():
    with session_scope() as session:
        session.query(StopWord).delete()
        session.query(BotConfig).delete()
        session.query(TrustedUser).delete()
        session.query(Member).delete()
        session.query(ModerationLog).delete()
    yield


# --- stopwords_repo ---


def test_add_stopword_normalizes_and_lists():
    assert stopwords_repo.add_stopword("  КАЗИНО  ", added_by="test") is True
    assert stopwords_repo.list_stopwords() == ["казино"]


def test_add_stopword_duplicate_returns_false():
    stopwords_repo.add_stopword("казино", added_by="test")
    assert stopwords_repo.add_stopword("казино", added_by="test2") is False
    assert stopwords_repo.list_stopwords() == ["казино"]


def test_add_stopword_empty_is_noop():
    assert stopwords_repo.add_stopword("   ", added_by="test") is False
    assert stopwords_repo.list_stopwords() == []


def test_remove_stopword_existing():
    stopwords_repo.add_stopword("казино", added_by="test")
    assert stopwords_repo.remove_stopword("КАЗИНО") is True
    assert stopwords_repo.list_stopwords() == []


def test_remove_stopword_missing_returns_false():
    assert stopwords_repo.remove_stopword("нет такого") is False


def test_list_stopwords_sorted():
    stopwords_repo.add_stopword("яблоко", added_by="test")
    stopwords_repo.add_stopword("апельсин", added_by="test")
    assert stopwords_repo.list_stopwords() == ["апельсин", "яблоко"]


# --- domains_repo ---


def test_add_domain_normalizes_strips_www():
    domain = domains_repo.add_allowed_domain("WWW.Example.COM", updated_by="test")
    assert domain == "example.com"
    assert domains_repo.list_allowed_domains() == ["example.com"]


def test_add_domain_dedups():
    domains_repo.add_allowed_domain("example.com", updated_by="test")
    domains_repo.add_allowed_domain("example.com", updated_by="test")
    assert domains_repo.list_allowed_domains() == ["example.com"]


def test_add_domain_empty_or_www_only_is_noop():
    assert domains_repo.add_allowed_domain("   ", updated_by="test") == ""
    assert domains_repo.add_allowed_domain("www.", updated_by="test") == ""
    assert domains_repo.list_allowed_domains() == []


def test_remove_domain_existing():
    domains_repo.add_allowed_domain("example.com", updated_by="test")
    assert domains_repo.remove_allowed_domain("example.com", updated_by="test") is True
    assert domains_repo.list_allowed_domains() == []


def test_remove_domain_missing_returns_false():
    assert domains_repo.remove_allowed_domain("nope.com", updated_by="test") is False


def test_list_allowed_domains_empty_by_default():
    assert domains_repo.list_allowed_domains() == []


# --- trusted_repo ---


def test_add_trusted_creates_row_and_syncs_member():
    with session_scope() as session:
        session.add(Member(user_id=42, chat_id=-100, is_trusted=False))
    assert trusted_repo.add_trusted(42, -100, added_by="test", reason="friend") is True
    with session_scope() as session:
        member = (
            session.query(Member)
            .filter(Member.user_id == 42, Member.chat_id == -100)
            .one()
        )
        assert member.is_trusted is True
        log = (
            session.query(ModerationLog)
            .filter(ModerationLog.user_id == 42, ModerationLog.action == "trust")
            .one()
        )
        assert log.reason == "friend"


def test_add_trusted_duplicate_returns_false():
    trusted_repo.add_trusted(42, -100, added_by="test")
    assert trusted_repo.add_trusted(42, -100, added_by="test2") is False


def test_add_trusted_works_without_existing_member_row():
    """Пользователь может быть добавлен в доверенные, даже если ещё не
    зарегистрирован как Member (например через веб-панель по числовому id)."""
    assert trusted_repo.add_trusted(999, -100, added_by="webui") is True
    assert len(trusted_repo.list_trusted(-100)) == 1


def test_remove_trusted_syncs_member():
    with session_scope() as session:
        session.add(Member(user_id=42, chat_id=-100, is_trusted=True))
    trusted_repo.add_trusted(42, -100, added_by="test")
    assert trusted_repo.remove_trusted(42, -100, actor="test") is True
    with session_scope() as session:
        member = (
            session.query(Member)
            .filter(Member.user_id == 42, Member.chat_id == -100)
            .one()
        )
        assert member.is_trusted is False


def test_remove_trusted_missing_returns_false():
    assert trusted_repo.remove_trusted(42, -100, actor="test") is False


def test_list_trusted_scoped_to_chat():
    trusted_repo.add_trusted(1, -100, added_by="test")
    trusted_repo.add_trusted(2, -200, added_by="test")
    assert [t.user_id for t in trusted_repo.list_trusted(-100)] == [1]
