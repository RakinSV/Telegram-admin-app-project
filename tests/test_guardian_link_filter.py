"""Тесты фильтра ссылок Guardian (G04) — видимые URL и скрытые text_link entities."""

from types import SimpleNamespace

from guardian.db.models import AllowedDomain
from guardian.db.session import session_scope
from guardian.filters.link_filter import LinkFilter, _domain_from_url

_CHAT_ID = -100123
_OTHER_CHAT_ID = -100999


def _clear_domains() -> None:
    with session_scope() as session:
        session.query(AllowedDomain).delete()


def _message(text: str = "", entities: list | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        text=text, caption=None, entities=entities, caption_entities=None
    )


def test_domain_from_url_strips_www():
    assert _domain_from_url("https://www.example.com/path") == "example.com"


def test_domain_from_url_handles_scheme_less():
    assert _domain_from_url("t.me/somechannel") == "t.me"


def test_link_filter_no_whitelist_flags_any_link():
    _clear_domains()
    lf = LinkFilter()
    with session_scope() as session:
        lf.reload(session)
    is_bad, domain = lf.check(
        _message(text="Заходи на https://spam-example.com сейчас"), _CHAT_ID
    )
    assert is_bad is True
    assert domain == "spam-example.com"


def test_link_filter_allows_whitelisted_domain():
    _clear_domains()
    with session_scope() as session:
        session.add(
            AllowedDomain(domain="example.com", chat_id=_CHAT_ID, added_by="test")
        )
    lf = LinkFilter()
    with session_scope() as session:
        lf.reload(session)
    is_bad, domain = lf.check(_message(text="See https://example.com/page"), _CHAT_ID)
    assert (is_bad, domain) == (False, None)


def test_link_filter_whitelist_scoped_to_its_own_chat():
    """F28: домен, разрешённый в одной группе, не должен быть разрешён в другой."""
    _clear_domains()
    with session_scope() as session:
        session.add(
            AllowedDomain(domain="example.com", chat_id=_CHAT_ID, added_by="test")
        )
    lf = LinkFilter()
    with session_scope() as session:
        lf.reload(session)
    is_bad, domain = lf.check(
        _message(text="See https://example.com/page"), _OTHER_CHAT_ID
    )
    assert is_bad is True
    assert domain == "example.com"


def test_link_filter_no_links_passes():
    _clear_domains()
    lf = LinkFilter()
    with session_scope() as session:
        lf.reload(session)
    assert lf.check(_message(text="Обычное сообщение без ссылок"), _CHAT_ID) == (
        False,
        None,
    )


def test_link_filter_detects_hidden_text_link_entity():
    _clear_domains()
    lf = LinkFilter()
    with session_scope() as session:
        lf.reload(session)
    entity = SimpleNamespace(type="text_link", url="https://hidden-spam.example")
    is_bad, domain = lf.check(
        _message(text="Нажми сюда", entities=[entity]), _CHAT_ID
    )
    assert is_bad is True
    assert domain == "hidden-spam.example"


def test_link_filter_tme_link_checked_like_any_domain():
    _clear_domains()
    lf = LinkFilter()
    with session_scope() as session:
        lf.reload(session)
    is_bad, domain = lf.check(
        _message(text="Подпишись t.me/othersuspiciouschannel"), _CHAT_ID
    )
    assert is_bad is True
    assert domain == "t.me"
