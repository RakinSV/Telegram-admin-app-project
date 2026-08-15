"""Поддержка: единый инбокс обращений (F68).

Главное, что защищаем — модель «один тред на человека». Человек не мыслит
тикетами: пишет, дописывает, возвращается через неделю. Нарезка на
отдельные обращения породила бы три треда об одном и том же и заставила
оператора собирать историю по кускам.

Второе — порядок в инбоксе: оператор открывает страницу, чтобы увидеть,
кому ещё не ответили, а не чтобы листать историю.
"""

from __future__ import annotations

import pytest

from tg_repost import support_repo as repo
from tg_repost.db.models import SupportMessage, SupportThread
from tg_repost.db.session import session_scope

ALICE = 5001
BOB = 5002


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(SupportMessage).delete()
            session.query(SupportThread).delete()

    _wipe()
    yield
    _wipe()


# --- один тред на человека ---


def test_second_message_joins_the_same_thread():
    """ГЛАВНАЯ МОДЕЛЬ. Человек дописывает — это тот же разговор."""
    first = repo.record_incoming(ALICE, "Здравствуйте")
    second = repo.record_incoming(ALICE, "Забыл добавить: заказ №5")

    assert first == second
    assert len(repo.messages_of(first)) == 2


def test_different_people_get_different_threads():
    assert repo.record_incoming(ALICE, "вопрос") != repo.record_incoming(BOB, "вопрос")


def test_new_message_reopens_closed_thread():
    """Человек вернулся с тем же вопросом.

    Оставить тред закрытым значило бы потерять обращение: оператор смотрит
    открытые, а этот в них не попадёт.
    """
    thread_id = repo.record_incoming(ALICE, "первый вопрос")
    repo.set_status(thread_id, repo.STATUS_CLOSED)

    repo.record_incoming(ALICE, "ещё вопрос")

    assert repo.get_thread(thread_id).status == repo.STATUS_OPEN


def test_username_is_refreshed_on_new_message():
    """Люди меняют @username, и старый в инбоксе бесполезен."""
    thread_id = repo.record_incoming(ALICE, "привет", username="old")
    repo.record_incoming(ALICE, "ещё", username="new")

    assert repo.get_thread(thread_id).username == "new"


def test_empty_message_creates_nothing():
    """Пустой тред в инбоксе выглядел бы как забытое обращение."""
    assert repo.record_incoming(ALICE, "   ") is None
    assert repo.list_threads() == []


def test_long_message_is_trimmed():
    thread_id = repo.record_incoming(ALICE, "а" * 10_000)

    assert len(repo.messages_of(thread_id)[0].text) == repo.MAX_TEXT


# --- непрочитанное ---


def test_incoming_marks_thread_unread():
    thread_id = repo.record_incoming(ALICE, "вопрос")

    assert repo.get_thread(thread_id).has_unread is True
    assert repo.unread_count() == 1


def test_reply_clears_unread():
    """Ответили — значит прочитали. Отдельно снимать флаг не нужно, и
    забыть это сделать тоже нельзя."""
    thread_id = repo.record_incoming(ALICE, "вопрос")

    repo.record_reply(thread_id, "отвечаю", author="owner")

    assert repo.get_thread(thread_id).has_unread is False


def test_mark_read_without_reply():
    """Оператор посмотрел и отложил — это его решение, а не факт открытия
    страницы."""
    thread_id = repo.record_incoming(ALICE, "вопрос")

    repo.mark_read(thread_id)

    assert repo.get_thread(thread_id).has_unread is False


def test_new_message_after_reply_marks_unread_again():
    thread_id = repo.record_incoming(ALICE, "вопрос")
    repo.record_reply(thread_id, "ответ", author="owner")

    repo.record_incoming(ALICE, "а ещё")

    assert repo.get_thread(thread_id).has_unread is True


def test_closing_clears_unread():
    thread_id = repo.record_incoming(ALICE, "вопрос")

    repo.set_status(thread_id, repo.STATUS_CLOSED)

    assert repo.unread_count() == 0


# --- ответы ---


def test_reply_is_stored_with_author():
    thread_id = repo.record_incoming(ALICE, "вопрос")
    repo.record_reply(thread_id, "ответ", author="editor1")

    messages = repo.messages_of(thread_id)

    assert messages[1].direction == repo.DIRECTION_OUT
    assert messages[1].author == "editor1"


def test_empty_reply_is_rejected():
    thread_id = repo.record_incoming(ALICE, "вопрос")

    assert repo.record_reply(thread_id, "  ", author="owner") is False


def test_reply_to_missing_thread_is_false():
    assert repo.record_reply(999999, "ответ", author="owner") is False


def test_messages_are_in_chronological_order():
    thread_id = repo.record_incoming(ALICE, "первое")
    repo.record_reply(thread_id, "ответ", author="owner")
    repo.record_incoming(ALICE, "второе")

    texts = [m.text for m in repo.messages_of(thread_id)]

    assert texts == ["первое", "ответ", "второе"]


# --- инбокс ---


def test_unanswered_come_first():
    """Оператор открывает страницу, чтобы увидеть, кому не ответили."""
    answered = repo.record_incoming(ALICE, "вопрос")
    repo.record_reply(answered, "ответ", author="owner")
    unanswered = repo.record_incoming(BOB, "вопрос")

    assert [t.id for t in repo.list_threads()][0] == unanswered


def test_filter_by_status():
    open_thread = repo.record_incoming(ALICE, "вопрос")
    closed = repo.record_incoming(BOB, "вопрос")
    repo.set_status(closed, repo.STATUS_CLOSED)

    assert [t.id for t in repo.list_threads(repo.STATUS_OPEN)] == [open_thread]
    assert [t.id for t in repo.list_threads(repo.STATUS_CLOSED)] == [closed]


def test_message_count_is_shown():
    thread_id = repo.record_incoming(ALICE, "раз")
    repo.record_incoming(ALICE, "два")
    repo.record_reply(thread_id, "три", author="owner")

    assert repo.list_threads()[0].message_count == 3


def test_unknown_status_is_rejected():
    thread_id = repo.record_incoming(ALICE, "вопрос")

    assert repo.set_status(thread_id, "какой-то") is False


def test_missing_thread_reads_as_none():
    assert repo.get_thread(999999) is None
    assert repo.messages_of(999999) == []
