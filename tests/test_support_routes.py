"""Веб-инбокс поддержки (F68).

Главное в UI: карточка человека показывается РЯДОМ с перепиской. Отвечать
незнакомцу и отвечать тому, кто привёл вам десять друзей, — разные
разговоры, и оператор должен видеть разницу не переключая страницы.
"""

from __future__ import annotations

import re

import pytest

from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401
from tg_repost import contacts_repo, support_repo
from tg_repost.db.models import ContactTag, SupportMessage, SupportThread
from tg_repost.db.session import session_scope

ALICE = 6001


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(SupportMessage).delete()
            session.query(SupportThread).delete()
            session.query(ContactTag).delete()

    _wipe()
    yield
    _wipe()


@pytest.fixture
def _no_send(monkeypatch):
    """Отправку глушим: токена Engage в тестах нет, а сеть тут ни при чём."""
    sent: list[tuple[int, str]] = []

    async def _fake(user_id, text):
        sent.append((user_id, text))
        return True

    monkeypatch.setattr(
        "tg_repost.webui.support_routes._send_reply", _fake, raising=True,
    )
    return sent


def test_inbox_opens_when_empty():
    client = _client()
    _bootstrap(client)

    assert client.get("/support").status_code == 200


def test_inbox_shows_unanswered_marker():
    client = _client()
    _bootstrap(client)
    support_repo.record_incoming(ALICE, "вопрос", username="alice")

    response = client.get("/support")

    assert "@alice" in response.text
    assert "без ответа: 1" in response.text


def test_thread_page_shows_conversation_and_card():
    client = _client()
    _bootstrap(client)
    thread_id = support_repo.record_incoming(ALICE, "мой вопрос")
    contacts_repo.add_tag(ALICE, "vip")

    response = client.get(f"/support/{thread_id}")

    assert response.status_code == 200
    assert "мой вопрос" in response.text
    assert "vip" in response.text  # карточка рядом с перепиской
    assert f"/contacts/{ALICE}" in response.text


def test_opening_thread_marks_it_read():
    client = _client()
    _bootstrap(client)
    thread_id = support_repo.record_incoming(ALICE, "вопрос")

    client.get(f"/support/{thread_id}")

    assert support_repo.get_thread(thread_id).has_unread is False


def test_reply_is_sent_and_stored(_no_send):
    client = _client()
    _bootstrap(client)
    thread_id = support_repo.record_incoming(ALICE, "вопрос")

    response = client.post(
        f"/support/{thread_id}/reply", data={"text": "вот ответ"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert _no_send == [(ALICE, "вот ответ")]
    assert support_repo.messages_of(thread_id)[-1].text == "вот ответ"


def test_reply_is_kept_even_when_sending_fails(monkeypatch):
    """Оператор потратил время на ответ.

    Потерять его текст из-за сетевой ошибки хуже, чем показать
    предупреждение и дать отправить снова.
    """
    client = _client()
    _bootstrap(client)
    thread_id = support_repo.record_incoming(ALICE, "вопрос")

    async def _fail(user_id, text):
        return False

    monkeypatch.setattr(
        "tg_repost.webui.support_routes._send_reply", _fail, raising=True,
    )

    client.post(
        f"/support/{thread_id}/reply", data={"text": "не дойдёт"},
        follow_redirects=False,
    )

    assert support_repo.messages_of(thread_id)[-1].text == "не дойдёт"


def test_empty_reply_changes_nothing(_no_send):
    client = _client()
    _bootstrap(client)
    thread_id = support_repo.record_incoming(ALICE, "вопрос")

    client.post(
        f"/support/{thread_id}/reply", data={"text": "   "}, follow_redirects=False,
    )

    assert len(support_repo.messages_of(thread_id)) == 1


def test_close_and_reopen():
    client = _client()
    _bootstrap(client)
    thread_id = support_repo.record_incoming(ALICE, "вопрос")

    client.post(f"/support/{thread_id}/close", follow_redirects=False)
    assert support_repo.get_thread(thread_id).status == support_repo.STATUS_CLOSED

    client.post(f"/support/{thread_id}/reopen", follow_redirects=False)
    assert support_repo.get_thread(thread_id).status == support_repo.STATUS_OPEN


def test_missing_thread_redirects_to_inbox():
    client = _client()
    _bootstrap(client)

    response = client.get("/support/999999", follow_redirects=False)

    assert response.status_code == 303


def test_requires_login():
    client = _client()

    assert client.get("/support", follow_redirects=False).status_code in (302, 303, 307)


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_no_missing_translations(lang):
    client = _client()
    _bootstrap(client)
    thread_id = support_repo.record_incoming(ALICE, "вопрос", username="alice")
    support_repo.record_reply(thread_id, "ответ", author="owner")

    client.get(f"/lang/{lang}?next=/support", follow_redirects=False)
    inbox = client.get("/support")
    thread = client.get(f"/support/{thread_id}")

    missing = re.compile(r"\[[a-z_]+\.[a-z_]+\]")
    assert not missing.findall(inbox.text), f"инбокс ({lang})"
    assert not missing.findall(thread.text), f"тред ({lang})"
