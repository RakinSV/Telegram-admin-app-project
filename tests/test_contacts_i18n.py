"""Полнота переводов страниц CRM (F63).

Отсутствующий ключ рендерится как `[ключ]` — не падает, а молча портит
страницу. Именно поэтому на него нужен тест: без него забытый перевод
доживёт до пользователя, и увидит его владелец, а не разработчик.

Проверяются ОБЕ локали: русская обычно заполняется по ходу работы, а
английская — потом и на бегу.
"""

from __future__ import annotations

import re

import pytest

from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401
from tg_repost import contacts_repo, segments_repo
from tg_repost.db.models import ContactSegment, ContactTag
from tg_repost.db.session import session_scope

# Ключ, оставшийся без перевода, выглядит как [contacts.something].
_MISSING = re.compile(r"\[[a-z_]+\.[a-z_]+\]")

PAGES = ("/contacts", "/contacts/424242", "/segments")


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(ContactTag).delete()
            session.query(ContactSegment).delete()

    _wipe()
    yield
    _wipe()


@pytest.mark.parametrize("lang", ["ru", "en"])
@pytest.mark.parametrize("url", PAGES)
def test_pages_have_no_missing_translations(lang, url):
    client = _client()
    _bootstrap(client)
    # Наполняем страницы данными: пустая страница не отрисует половину строк,
    # и тест был бы зелёным при забытом переводе.
    contacts_repo.add_tag(424242, "vip")
    contacts_repo.set_note(424242, "заметка")
    segments_repo.save("Тестовый", {"tag": "vip"})

    client.get(f"/lang/{lang}?next=/contacts", follow_redirects=False)
    response = client.get(url)

    assert response.status_code == 200
    missing = _MISSING.findall(response.text)
    assert not missing, f"{url} ({lang}): забыты переводы {sorted(set(missing))}"


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_navigation_links_are_translated(lang):
    client = _client()
    _bootstrap(client)

    client.get(f"/lang/{lang}?next=/contacts", follow_redirects=False)
    response = client.get("/contacts")

    assert "[nav.contacts]" not in response.text
    assert "[nav.segments]" not in response.text
    assert 'href="/contacts"' in response.text
    assert 'href="/segments"' in response.text
