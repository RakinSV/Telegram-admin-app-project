"""Заявки рекламодателей и бронь мест (F66).

Главное, что защищаем — НЕВОЗМОЖНОСТЬ ПРОДАТЬ ОДНО МЕСТО ДВАЖДЫ. Две
принятые заявки на одну дату означают, что владелец пообещал одно и то же
двоим, и узнает об этом кто-то из них уже после оплаты. Извинением такое не
исправляется.

Второе по важности — цепочка «заявка → бриф → доход». Она существует, чтобы
вопрос «сколько мы заработали на этом рекламодателе» перестал быть вопросом
к памяти.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from tg_repost import ad_requests_repo as repo
from tg_repost.db.models import AdBrief, AdRequest, AdRevenue
from tg_repost.db.session import session_scope

CHAT = -100777777
OTHER_CHAT = -100888888
DAY = date(2026, 9, 1)


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(AdRequest).delete()
            session.query(AdRevenue).delete()
            session.query(AdBrief).delete()

    _wipe()
    yield
    _wipe()


def _create(
    *, advertiser: str = "@shop", slot: date = DAY, chat_id: int = CHAT,
    price: float | None = 5000.0,
) -> int:
    request_id = repo.create(
        chat_id=chat_id, advertiser=advertiser,
        brief_text="Расскажите про наш магазин", slot_date=slot, price=price,
    )
    assert request_id is not None
    return request_id


# --- создание ---


def test_create_and_read_back():
    request_id = _create()

    view = repo.get(request_id)

    assert view is not None
    assert view.advertiser == "@shop"
    assert view.status == repo.STATUS_NEW
    assert view.slot_date == DAY


def test_empty_fields_are_rejected():
    assert repo.create(
        chat_id=CHAT, advertiser="  ", brief_text="текст", slot_date=DAY,
    ) is None
    assert repo.create(
        chat_id=CHAT, advertiser="@shop", brief_text="  ", slot_date=DAY,
    ) is None


def test_several_requests_may_compete_for_one_date():
    """Заявка — это просьба, а не бронь.

    Отвергать входящие за владельца значило бы терять деньги на ровном
    месте: пусть придут трое на одну дату, выберет он сам.
    """
    _create(advertiser="@first")
    _create(advertiser="@second")

    assert len(repo.list_all(CHAT)) == 2


# --- двойная продажа ---


def test_accept_blocks_second_request_on_same_date():
    """ГЛАВНЫЙ ТЕСТ ФАЙЛА."""
    first = _create(advertiser="@first")
    second = _create(advertiser="@second")
    repo.accept(first)

    with pytest.raises(repo.SlotTaken) as exc:
        repo.accept(second)

    # Исключение несёт САМУ конфликтующую заявку: владельцу решать, кому
    # отказать, и для этого надо видеть, кто там стоит.
    assert exc.value.existing.advertiser == "@first"
    assert repo.get(second).status == repo.STATUS_NEW


def test_published_slot_also_blocks_the_date():
    first = _create(advertiser="@first")
    repo.accept(first)
    repo.mark_published(first)
    second = _create(advertiser="@second")

    with pytest.raises(repo.SlotTaken):
        repo.accept(second)


def test_declined_request_frees_the_date():
    """Отказ не должен блокировать день навсегда."""
    first = _create(advertiser="@first")
    repo.decline(first)
    second = _create(advertiser="@second")

    assert repo.accept(second) is not None


def test_same_date_in_another_channel_is_fine():
    """Каналы независимы: одна дата — разные сетки."""
    first = _create(chat_id=CHAT)
    second = _create(chat_id=OTHER_CHAT)
    repo.accept(first)

    assert repo.accept(second) is not None


def test_neighbouring_dates_do_not_conflict():
    first = _create(slot=DAY)
    second = _create(slot=DAY + timedelta(days=1))
    repo.accept(first)

    assert repo.accept(second) is not None


# --- цепочка заявка → бриф → доход ---


def test_accept_creates_brief_limited_to_one_use():
    """Заявка оплачена за ОДНО размещение.

    Бриф без лимита ИИ взял бы повторно — то есть выдал бы рекламодателю
    бесплатное размещение за наш счёт.
    """
    request_id = _create()

    brief_id = repo.accept(request_id)

    with session_scope() as session:
        brief = session.get(AdBrief, brief_id)
        assert brief is not None
        assert brief.max_uses == 1
        assert brief.brief_text == "Расскажите про наш магазин"
    assert repo.get(request_id).ad_brief_id == brief_id


def test_publish_records_revenue_linked_to_the_brief():
    request_id = _create(price=5000.0)
    brief_id = repo.accept(request_id)

    revenue_id = repo.mark_published(request_id)

    with session_scope() as session:
        revenue = session.get(AdRevenue, revenue_id)
        assert revenue is not None
        assert revenue.amount == 5000.0
        assert revenue.source == "@shop"
        assert revenue.ad_brief_id == brief_id  # цепочка не рвётся
    assert repo.get(request_id).status == repo.STATUS_PUBLISHED


def test_publish_can_override_the_agreed_price():
    """Договорились на одну сумму, получили другую — врать журналу незачем."""
    request_id = _create(price=5000.0)
    repo.accept(request_id)

    revenue_id = repo.mark_published(request_id, amount=4200.0)

    with session_scope() as session:
        assert session.get(AdRevenue, revenue_id).amount == 4200.0


def test_publish_without_price_still_moves_status():
    """Размещение состоялось, даже если сумму внесут потом руками."""
    request_id = _create(price=None)
    repo.accept(request_id)

    assert repo.mark_published(request_id) is None
    assert repo.get(request_id).status == repo.STATUS_PUBLISHED


# --- переходы статусов ---


def test_cannot_accept_twice():
    request_id = _create()
    repo.accept(request_id)

    assert repo.accept(request_id) is None


def test_cannot_publish_unaccepted_request():
    request_id = _create()

    assert repo.mark_published(request_id) is None


def test_cannot_decline_accepted_request():
    request_id = _create()
    repo.accept(request_id)

    assert repo.decline(request_id) is False


def test_published_request_cannot_be_deleted():
    """За опубликованной стоит запись дохода — удаление порвало бы отчётность."""
    request_id = _create()
    repo.accept(request_id)
    repo.mark_published(request_id)

    assert repo.delete(request_id) is False


def test_new_request_can_be_deleted():
    request_id = _create()

    assert repo.delete(request_id) is True
    assert repo.get(request_id) is None


# --- календарь ---


def test_occupied_dates_lists_only_booked_slots():
    accepted = _create(advertiser="@accepted", slot=DAY)
    repo.accept(accepted)
    _create(advertiser="@pending", slot=DAY + timedelta(days=2))
    declined = _create(advertiser="@declined", slot=DAY + timedelta(days=3))
    repo.decline(declined)

    occupied = repo.occupied_dates(CHAT)

    assert list(occupied) == [DAY]
    assert occupied[DAY].advertiser == "@accepted"


def test_occupied_dates_are_per_channel():
    mine = _create(chat_id=CHAT)
    theirs = _create(chat_id=OTHER_CHAT)
    repo.accept(mine)
    repo.accept(theirs)

    assert list(repo.occupied_dates(CHAT)) == [DAY]
    assert list(repo.occupied_dates(OTHER_CHAT)) == [DAY]


def test_list_filters_by_status():
    new_one = _create(advertiser="@new")
    accepted = _create(advertiser="@accepted", slot=DAY + timedelta(days=1))
    repo.accept(accepted)

    assert [r.id for r in repo.list_all(CHAT, status=repo.STATUS_NEW)] == [new_one]
