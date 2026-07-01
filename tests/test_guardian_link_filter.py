"""Тесты фильтра ссылок Guardian (G04) — видимые URL и скрытые text_link entities."""

from types import SimpleNamespace

from guardian.db.models import BotConfig
from guardian.db.session import session_scope
from guardian.filters.link_filter import LinkFilter, _domain_from_url


def _clear_config() -> None:
    with session_scope() as session:
        session.query(BotConfig).delete()


def _message(text: str = "", entities: list | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        text=text, caption=None, entities=entities, caption_entities=None
    )


def test_domain_from_url_strips_www():
    assert _domain_from_url("https://www.example.com/path") == "example.com"


def test_domain_from_url_handles_scheme_less():
    assert _domain_from_url("t.me/somechannel") == "t.me"


def test_link_filter_no_whitelist_flags_any_link():
    _clear_config()
    lf = LinkFilter()
    with session_scope() as session:
        lf.reload(session)
    is_bad, domain = lf.check(
        _message(text="Заходи на https://spam-example.com сейчас")
    )
    assert is_bad is True
    assert domain == "spam-example.com"


def test_link_filter_allows_whitelisted_domain():
    _clear_config()
    with session_scope() as session:
        session.add(
            BotConfig(key="allowed_domains", value='["example.com"]', updated_by="test")
        )
    lf = LinkFilter()
    with session_scope() as session:
        lf.reload(session)
    is_bad, domain = lf.check(_message(text="See https://example.com/page"))
    assert (is_bad, domain) == (False, None)


def test_link_filter_no_links_passes():
    _clear_config()
    lf = LinkFilter()
    with session_scope() as session:
        lf.reload(session)
    assert lf.check(_message(text="Обычное сообщение без ссылок")) == (False, None)


def test_link_filter_detects_hidden_text_link_entity():
    _clear_config()
    lf = LinkFilter()
    with session_scope() as session:
        lf.reload(session)
    entity = SimpleNamespace(type="text_link", url="https://hidden-spam.example")
    is_bad, domain = lf.check(_message(text="Нажми сюда", entities=[entity]))
    assert is_bad is True
    assert domain == "hidden-spam.example"


def test_link_filter_tme_link_checked_like_any_domain():
    _clear_config()
    lf = LinkFilter()
    with session_scope() as session:
        lf.reload(session)
    is_bad, domain = lf.check(_message(text="Подпишись t.me/othersuspiciouschannel"))
    assert is_bad is True
    assert domain == "t.me"
