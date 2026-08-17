"""Одновременная покупка последнего товара (аудит 2026-08-17).

НАЙДЕНО ОПЫТОМ, А НЕ ЧТЕНИЕМ. Списание было обычным `product.stock -=
quantity`: сессия читает остаток, вычитает в памяти, пишет обратно. Две
перекрывающиеся сессии читают 5, каждая пишет 4 — после двух покупок на
складе 4 вместо 3, один товар продан бесплатно.

Хуже самой потери: флаг «продано сверх остатка» при этом НЕ срабатывает — он
сравнивает с тем же устаревшим значением. То есть тихо ломается ровно та
гарантия, которую я описал в F69 как главную.

Тесты воспроизводят перекрытие двумя настоящими сессиями: имитировать гонку
моками бессмысленно, потому что проверяется поведение базы, а не кода.
"""

from __future__ import annotations

import pytest

from tg_repost import shop_repo as shop
from tg_repost.db.models import Order, Product
from tg_repost.db.session import SessionLocal, session_scope

ALICE = 9901
BOB = 9902


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(Order).delete()
            session.query(Product).delete()

    _wipe()
    yield
    _wipe()


def _product(stock: int) -> int:
    return shop.save_product(name="Кружка", price=100000, stock=stock, is_active=True)


def _stock(product_id: int) -> int | None:
    view = shop.get_product(product_id)
    return view.stock if view else None


# --- сама гонка ---


def test_two_overlapping_sessions_do_not_lose_stock():
    """ГЛАВНАЯ ПРОВЕРКА.

    Обе сессии читают остаток ДО того, как любая из них записала, — ровно
    как два процесса, обслуживающих двух покупателей одновременно.
    """
    product_id = _product(stock=5)

    first, second = SessionLocal(), SessionLocal()
    try:
        pa = first.get(Product, product_id)
        pb = second.get(Product, product_id)

        assert shop._take_from_stock(first, pa, 1) is True
        first.commit()
        assert shop._take_from_stock(second, pb, 1) is True
        second.commit()
    finally:
        first.close()
        second.close()

    assert _stock(product_id) == 3, "одна покупка потерялась"


def test_second_buyer_of_the_last_item_is_refused():
    """Последний товар нельзя списать дважды: условие проверяет база в момент
    записи, а не мы по устаревшему значению."""
    product_id = _product(stock=1)

    first, second = SessionLocal(), SessionLocal()
    try:
        pa = first.get(Product, product_id)
        pb = second.get(Product, product_id)

        assert shop._take_from_stock(first, pa, 1) is True
        first.commit()
        refused = shop._take_from_stock(second, pb, 1)
        second.commit()
    finally:
        first.close()
        second.close()

    assert refused is False
    assert _stock(product_id) == 0


def test_unlimited_stock_needs_no_bookkeeping():
    product_id = shop.save_product(
        name="Услуга", price=100000, stock=None, is_active=True,
    )

    with session_scope() as session:
        product = session.get(Product, product_id)

        assert shop._take_from_stock(session, product, 100) is True

    assert _stock(product_id) is None


def test_request_larger_than_stock_is_refused_whole():
    """Частично списывать нельзя: заказ либо собран, либо нет."""
    product_id = _product(stock=2)

    with session_scope() as session:
        product = session.get(Product, product_id)

        assert shop._take_from_stock(session, product, 3) is False

    assert _stock(product_id) == 2, "остаток тронули при отказе"


def test_in_memory_value_is_refreshed():
    """После прямого UPDATE значение в памяти устаревает — та же ловушка,
    что уже ловили в очереди задач."""
    product_id = _product(stock=5)

    with session_scope() as session:
        product = session.get(Product, product_id)
        shop._take_from_stock(session, product, 2)

        assert product.stock == 3


# --- через обычный путь оплаты ---


def test_paid_orders_keep_the_stock_honest():
    product_id = _product(stock=3)

    shop.record_paid_order(
        user_id=ALICE, product_id=product_id, amount=100000,
        currency="RUB", charge_id="a",
    )
    shop.record_paid_order(
        user_id=BOB, product_id=product_id, amount=100000,
        currency="RUB", charge_id="b",
    )

    assert _stock(product_id) == 1


def test_oversold_flag_still_works():
    """Гарантия, которую тихо ломало потерянное обновление."""
    product_id = _product(stock=1)

    shop.record_paid_order(
        user_id=ALICE, product_id=product_id, amount=100000,
        currency="RUB", charge_id="a",
    )
    second = shop.record_paid_order(
        user_id=BOB, product_id=product_id, amount=100000,
        currency="RUB", charge_id="b",
    )

    assert second is not None and second.is_oversold is True
