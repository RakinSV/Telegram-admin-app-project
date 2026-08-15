"""Веб-интерфейс заявок рекламодателей (F66).

Главное, что проверяем в UI: конфликт дат доходит до владельца ТЕКСТОМ С
ИМЕНЕМ, а не «дата занята». Владельцу решать, кому отказать, и для этого
надо видеть, кто там стоит — сообщение без имени превращает решение в
угадывание.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401
from tg_repost import ad_requests_repo as repo
from tg_repost import targets_repo
from tg_repost.db.models import AdBrief, AdRequest, AdRevenue, TargetGroup
from tg_repost.db.session import session_scope

CHAT = -100123123
DAY = date.today() + timedelta(days=3)


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(AdRequest).delete()
            session.query(AdRevenue).delete()
            session.query(AdBrief).delete()
            session.query(TargetGroup).delete()

    _wipe()
    yield
    _wipe()


def _channel() -> None:
    targets_repo.add_target(CHAT, "Мой канал")


def _request(advertiser: str = "@shop", slot: date = DAY) -> int:
    request_id = repo.create(
        chat_id=CHAT, advertiser=advertiser, brief_text="Про магазин",
        slot_date=slot, price=5000.0,
    )
    assert request_id is not None
    return request_id


# --- страница ---


def test_page_opens_without_channels():
    client = _client()
    _bootstrap(client)

    assert client.get("/ad-requests").status_code == 200


def test_page_shows_calendar_and_requests():
    client = _client()
    _bootstrap(client)
    _channel()
    _request()

    response = client.get(f"/ad-requests?chat_id={CHAT}")

    assert response.status_code == 200
    assert "@shop" in response.text
    assert DAY.strftime("%d.%m") in response.text  # день есть в сетке


def test_page_requires_login():
    client = _client()

    assert client.get("/ad-requests", follow_redirects=False).status_code in (
        302, 303, 307,
    )


# --- создание ---


def test_create_through_form():
    client = _client()
    _bootstrap(client)
    _channel()

    response = client.post(
        "/ad-requests",
        data={
            "chat_id": str(CHAT), "advertiser": "@newshop",
            "brief_text": "Текст брифа", "slot_date": DAY.isoformat(),
            "price": "7500",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    rows = repo.list_all(CHAT)
    assert len(rows) == 1
    assert rows[0].price == 7500.0


def test_comma_decimal_is_accepted():
    """«7500,50» — привычная запись, ронять на ней форму незачем."""
    client = _client()
    _bootstrap(client)
    _channel()

    client.post(
        "/ad-requests",
        data={
            "chat_id": str(CHAT), "advertiser": "@shop",
            "brief_text": "текст", "slot_date": DAY.isoformat(),
            "price": "7500,50",
        },
        follow_redirects=False,
    )

    assert repo.list_all(CHAT)[0].price == 7500.5


def test_bad_date_is_reported():
    client = _client()
    _bootstrap(client)
    _channel()

    response = client.post(
        "/ad-requests",
        data={
            "chat_id": str(CHAT), "advertiser": "@shop",
            "brief_text": "текст", "slot_date": "не дата",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert repo.list_all(CHAT) == []


def test_bad_price_is_reported():
    client = _client()
    _bootstrap(client)
    _channel()

    response = client.post(
        "/ad-requests",
        data={
            "chat_id": str(CHAT), "advertiser": "@shop",
            "brief_text": "текст", "slot_date": DAY.isoformat(),
            "price": "дорого",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert repo.list_all(CHAT) == []


# --- конфликт дат ---


def test_conflict_message_names_the_competitor():
    """ГЛАВНЫЙ ТЕСТ ФАЙЛА.

    «Дата занята» превращает решение в угадывание. Владельцу нужно имя, с
    кем конфликт, чтобы понять, кому отказывать.
    """
    client = _client()
    _bootstrap(client)
    _channel()
    first = _request("@first")
    second = _request("@second")
    repo.accept(first)

    response = client.post(
        f"/ad-requests/{second}/accept", follow_redirects=False,
    )

    assert response.status_code == 409
    assert "@first" in response.text
    assert repo.get(second).status == repo.STATUS_NEW


def test_accept_succeeds_on_free_date():
    client = _client()
    _bootstrap(client)
    _channel()
    request_id = _request()

    response = client.post(
        f"/ad-requests/{request_id}/accept", follow_redirects=False,
    )

    assert response.status_code == 303
    view = repo.get(request_id)
    assert view.status == repo.STATUS_ACCEPTED
    assert view.ad_brief_id is not None  # бриф создан


# --- остальные переходы ---


def test_decline_through_ui():
    client = _client()
    _bootstrap(client)
    _channel()
    request_id = _request()

    client.post(f"/ad-requests/{request_id}/decline", follow_redirects=False)

    assert repo.get(request_id).status == repo.STATUS_DECLINED


def test_publish_records_revenue():
    client = _client()
    _bootstrap(client)
    _channel()
    request_id = _request()
    repo.accept(request_id)

    client.post(
        f"/ad-requests/{request_id}/publish", data={"amount": ""},
        follow_redirects=False,
    )

    view = repo.get(request_id)
    assert view.status == repo.STATUS_PUBLISHED
    assert view.ad_revenue_id is not None


def test_publish_with_corrected_amount():
    client = _client()
    _bootstrap(client)
    _channel()
    request_id = _request()
    repo.accept(request_id)

    client.post(
        f"/ad-requests/{request_id}/publish", data={"amount": "4200"},
        follow_redirects=False,
    )

    with session_scope() as session:
        revenue = session.query(AdRevenue).one()
        assert revenue.amount == 4200.0


def test_delete_through_ui():
    client = _client()
    _bootstrap(client)
    _channel()
    request_id = _request()

    client.post(f"/ad-requests/{request_id}/delete", follow_redirects=False)

    assert repo.get(request_id) is None


# --- переводы ---


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_no_missing_translations(lang):
    import re

    client = _client()
    _bootstrap(client)
    _channel()
    request_id = _request()
    repo.accept(request_id)
    _request("@pending", slot=DAY + timedelta(days=1))

    client.get(f"/lang/{lang}?next=/ad-requests", follow_redirects=False)
    response = client.get(f"/ad-requests?chat_id={CHAT}")

    assert not re.compile(r"\[[a-z_]+\.[a-z_]+\]").findall(response.text)
