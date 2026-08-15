"""Реестр подписчиков бота (F64) — кому вообще можно написать.

Главное, что защищаем: ТРИ ПРИЧИНЫ недостижимости — не запускал бота,
заблокировал, отписался — это разные состояния с разными правилами. Если их
смешать, отписавшийся начнёт получать рассылки после того, как задаст боту
вопрос, а заблокировавшего система будет долбить вечно.

И вторая вещь: у рассылки всегда ДВЕ цифры. Сегмент из 8000 участников
группы может быть достижим на сотню человек — это правило Telegram, а не наш
сбой, и владелец обязан видеть разрыв ДО отправки.
"""

from __future__ import annotations

import pytest

from tg_repost import subscribers_repo as repo
from tg_repost.db.models import BotSubscriber
from tg_repost.db.session import session_scope

A, B, C, D = 9001, 9002, 9003, 9004


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(BotSubscriber).delete()

    _wipe()
    yield
    _wipe()


# --- запись контакта ---


def test_first_contact_creates_record():
    assert repo.record_contact(A, username="serega", first_name="Серёга") is True
    assert repo.is_reachable(A) is True


def test_repeat_contact_updates_instead_of_duplicating():
    repo.record_contact(A, username="old")

    assert repo.record_contact(A, username="new") is False

    with session_scope() as session:
        row = session.query(BotSubscriber).filter(BotSubscriber.user_id == A).one()
        assert row.username == "new"


def test_unknown_person_is_not_reachable():
    """Обычное состояние большинства участников группы, а не ошибка."""
    assert repo.is_reachable(A) is False


# --- три причины недостижимости, и они разные ---


def test_blocked_person_is_not_reachable():
    repo.record_contact(A)
    repo.mark_blocked(A)

    assert repo.is_reachable(A) is False


def test_message_from_person_clears_the_block():
    """Раз сообщение дошло — блокировки больше нет."""
    repo.record_contact(A)
    repo.mark_blocked(A)

    repo.record_contact(A)

    assert repo.is_reachable(A) is True


def test_unsubscribed_person_is_not_reachable():
    repo.record_contact(A)
    repo.unsubscribe(A)

    assert repo.is_reachable(A) is False


def test_writing_to_bot_does_not_cancel_unsubscribe():
    """САМОЕ ВАЖНОЕ РАЗЛИЧИЕ.

    Отписка — сознательное решение человека, а «написал боту» не значит
    «передумал». Если это смешать, любой вопрос боту вернёт человека в
    рассылку, от которой он отказался, — и следующая жалоба будет
    справедливой.
    """
    repo.record_contact(A)
    repo.unsubscribe(A)

    repo.record_contact(A)  # человек задал боту вопрос

    assert repo.is_reachable(A) is False


def test_resubscribe_restores_reachability():
    repo.record_contact(A)
    repo.unsubscribe(A)

    assert repo.resubscribe(A) is True
    assert repo.is_reachable(A) is True


def test_double_unsubscribe_is_reported():
    repo.record_contact(A)

    assert repo.unsubscribe(A) is True
    assert repo.unsubscribe(A) is False


def test_unsubscribe_unknown_person_is_false():
    assert repo.unsubscribe(A) is False


# --- отбор получателей ---


def test_reachable_among_filters_and_sorts():
    repo.record_contact(C)
    repo.record_contact(A)
    repo.record_contact(B)
    repo.mark_blocked(B)

    assert repo.reachable_among([A, B, C, D]) == [A, C]


def test_reachable_among_supports_resuming():
    """Продолжение прерванной рассылки — без повторов и пропусков.

    Сортировка по id делает порядок стабильным между запусками: тот, кто
    уже получил сообщение, остаётся позади курсора навсегда.
    """
    for user_id in (A, B, C):
        repo.record_contact(user_id)

    assert repo.reachable_among([A, B, C], after_user_id=A) == [B, C]
    assert repo.reachable_among([A, B, C], after_user_id=C) == []


def test_reachable_among_empty_input():
    assert repo.reachable_among([]) == []


# --- две цифры вместо одной ---


def test_reach_stats_explains_the_gap():
    """Владелец видит НЕ просто «достижимо 1», а почему остальные — нет.

    Без разбивки цифра «из 4 достижим 1» выглядит как поломка, хотя это
    нормальная работа Telegram.
    """
    repo.record_contact(A)                    # достижим
    repo.record_contact(B)
    repo.mark_blocked(B)                      # заблокировал бота
    repo.record_contact(C)
    repo.unsubscribe(C)                       # отписался сам
    # D бота вообще не запускал

    stats = repo.reach_stats([A, B, C, D])

    assert stats.total == 4
    assert stats.reachable == 1
    assert stats.blocked == 1
    assert stats.unsubscribed == 1
    assert stats.never_started == 1


def test_reach_stats_parts_sum_to_total():
    """Инвариант: каждый человек попадает ровно в одну категорию.

    Если бы категории пересекались, сумма разошлась бы с общим числом, и
    отчёт владельцу врал бы.
    """
    repo.record_contact(A)
    repo.record_contact(B)
    repo.mark_blocked(B)
    repo.record_contact(C)
    repo.unsubscribe(C)

    stats = repo.reach_stats([A, B, C, D])

    assert (
        stats.reachable + stats.blocked + stats.unsubscribed + stats.never_started
        == stats.total
    )


def test_blocked_and_unsubscribed_counted_once():
    """Человек, который и отписался, и заблокировал, не считается дважды."""
    repo.record_contact(A)
    repo.unsubscribe(A)
    repo.mark_blocked(A)

    stats = repo.reach_stats([A])

    assert stats.total == 1
    assert stats.reachable == 0
    assert stats.blocked + stats.unsubscribed == 1


def test_reach_stats_on_empty_selection():
    stats = repo.reach_stats([])

    assert stats.total == 0
    assert stats.reachable == 0
