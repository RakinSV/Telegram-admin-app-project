"""Админка магазина (F69).

Цена вводится в рублях, а хранится в копейках — ошибка на этом переводе даёт
товар за 1499 копеек вместо 1499 рублей, и заметно это станет только после
первой продажи.
"""

from __future__ import annotations

import re

import pytest

from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401
from tg_repost import shop_repo as shop
from tg_repost.db.models import AdminUser, Order, Product
from tg_repost.db.session import session_scope
from tg_repost.webui import access
from tg_repost.webui.auth import hash_password
from tg_repost.webui.shop_routes import rubles_to_minor

ALICE = 9701


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(Order).delete()
            session.query(Product).delete()

    _wipe()
    yield
    _wipe()


# --- перевод цены ---


@pytest.mark.parametrize("raw,expected", [
    ("1499", 149900),
    ("1499.90", 149990),
    ("1499,90", 149990),
    (" 1 499 ", 149900),
    ("0.99", 99),
])
def test_price_is_converted_to_minor_units(raw, expected):
    """Точка и запятая равноправны: отказ из-за разделителя выглядит
    придиркой, а владелец наберёт то, что привычно."""
    assert rubles_to_minor(raw) == expected


@pytest.mark.parametrize("raw", ["", "бесплатно", "0", "-5"])
def test_broken_price_is_rejected(raw):
    assert rubles_to_minor(raw) is None


# --- страница ---


def test_page_opens_when_empty():
    client = _client()
    _bootstrap(client)

    assert client.get("/shop").status_code == 200


def test_page_warns_that_shop_is_off():
    client = _client()
    _bootstrap(client)

    assert "выключен" in client.get("/shop").text


def test_product_is_created_hidden():
    """Товар не должен попадать в продажу в момент создания."""
    client = _client()
    _bootstrap(client)

    client.post("/shop/products", data={"name": "Кружка", "price": "1499"})

    products = shop.list_products()
    assert len(products) == 1
    assert products[0].price == 149900
    assert products[0].is_active is False


def test_bad_price_shows_an_error():
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/shop/products", data={"name": "Кружка", "price": "дорого"},
    )

    assert response.status_code == 400
    assert shop.list_products() == []


def test_product_can_be_published_and_hidden():
    client = _client()
    _bootstrap(client)
    product_id = shop.save_product(name="Кружка", price=149900, stock=5)

    client.post(f"/shop/products/{product_id}/toggle")
    assert shop.get_product(product_id).is_active is True

    client.post(f"/shop/products/{product_id}/toggle")
    assert shop.get_product(product_id).is_active is False


def test_sold_out_product_cannot_be_published():
    """Выставить в продажу то, чего нет, — обещание, которое не выполнить."""
    client = _client()
    _bootstrap(client)
    product_id = shop.save_product(name="Кружка", price=149900, stock=0)

    client.post(f"/shop/products/{product_id}/toggle", follow_redirects=False)

    assert shop.get_product(product_id).is_active is False


def test_order_can_be_marked_shipped():
    client = _client()
    _bootstrap(client)
    product_id = shop.save_product(name="Кружка", price=149900, is_active=True)
    order = shop.record_paid_order(
        user_id=ALICE, product_id=product_id, amount=149900,
        currency="RUB", charge_id="c1",
    )

    client.post(f"/shop/orders/{order.id}/status", data={"status": "shipped"})

    assert shop.list_orders()[0].status == shop.STATUS_SHIPPED


def test_oversold_order_is_visible_to_the_owner():
    """Владелец должен увидеть это сам, а не узнать от покупателя."""
    client = _client()
    _bootstrap(client)
    product_id = shop.save_product(name="Кружка", price=149900, stock=1)
    shop.record_paid_order(
        user_id=ALICE, product_id=product_id, amount=149900,
        currency="RUB", charge_id="c1",
    )
    shop.record_paid_order(
        user_id=9702, product_id=product_id, amount=149900,
        currency="RUB", charge_id="c2",
    )

    assert "сверх остатка" in client.get("/shop").text


def test_page_is_owner_only():
    """В заказах адреса и телефоны покупателей."""
    client = _client()
    _bootstrap(client)
    with session_scope() as session:
        session.add(AdminUser(
            username="editor_shop", role=access.ROLE_EDITOR,
            password_hash=hash_password("another-strong-pass"),
        ))
    client.post(
        "/login", data={"username": "editor_shop", "password": "another-strong-pass"},
        follow_redirects=False,
    )

    assert client.get("/shop").status_code == 403


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_no_missing_translations(lang):
    client = _client()
    _bootstrap(client)
    product_id = shop.save_product(name="Кружка", price=149900, is_active=True)
    shop.record_paid_order(
        user_id=ALICE, product_id=product_id, amount=149900,
        currency="RUB", charge_id="c1",
    )

    client.get(f"/lang/{lang}?next=/shop", follow_redirects=False)
    response = client.get("/shop")

    assert not re.compile(r"\[[a-z_]+\.[a-z_]+\]").findall(response.text)
