"""Два подтверждения одной крипто-оплаты (найдено замером 2026-08-19).

ЧТО БЫЛО. `mark_crypto_order_paid` сначала ЧИТАЛ статус заказа, потом
проверял его, потом списывал со склада. Два наложившихся подтверждения оба
читают «новый», оба проходят проверку и оба списывают: один товар уходит
бесплатно, а покупателю дважды приходит «оплата подтверждена». Замер на
файловой базе: остаток 5 → 3 вместо 4.

Ровно эту ошибку в этом же файле уже ловили на остатке — см. комментарий в
`_take_from_stock`: «две перекрывающиеся сессии читают остаток 5, каждая
пишет прочитанное минус один». Здесь она повторилась этажом выше, на статусе.

ПОЧЕМУ ТЕСТ БЕЗ ПОТОКОВ. В тестах база — `:memory:`, и движок намеренно даёт
ОДНО соединение на все потоки (`db/session.py`, StaticPool). Проверка
потоками там измеряла бы не код, а стенд. Поэтому наложение
воспроизводится точно: второй вызов делается ИЗНУТРИ первого, до того как
первый завершил свою сделку.

ПОЧЕМУ ЭТО НЕ «ТЕОРИЯ». Сегодня наложиться нечему: очередь строго
последовательна (`task_queue.run_pending` — while по одной задаче), а у
джобы `max_instances=1`. Но это свойство ПЛАНИРОВЩИКА, а не денег: оно
исчезнет от второго воркера или от кнопки «проверить оплату сейчас». Цена
ошибки — настоящие деньги и настоящий товар, поэтому защита стоит здесь, а
не полагается на расписание.
"""

from __future__ import annotations

import pytest

from tg_repost import shop_repo as shop
from tg_repost.db.models import Order, Product
from tg_repost.db.session import session_scope


@pytest.fixture
def product_and_order():
    with session_scope() as session:
        session.query(Order).delete()
        session.query(Product).delete()
        product = Product(name="Товар", price=100.0, currency="RUB",
                          is_active=True, stock=5)
        session.add(product)
        session.flush()
        product_id = product.id

    order = shop.create_crypto_order(
        user_id=77, product_id=product_id, rail_id=1,
        invoice_id="inv-race", crypto_amount="1.0", crypto_asset="USDT",
    )
    yield product_id, order.id

    with session_scope() as session:
        session.query(Order).delete()
        session.query(Product).delete()


def _stock(product_id: int) -> int:
    with session_scope() as session:
        return session.get(Product, product_id).stock


def test_second_confirmation_of_the_same_order_is_refused(product_and_order):
    """Простой случай: подтверждение пришло дважды подряд."""
    product_id, order_id = product_and_order

    first = shop.mark_crypto_order_paid(order_id)
    second = shop.mark_crypto_order_paid(order_id)

    assert first is not None
    assert second is None, "второе подтверждение прошло как первое"
    assert _stock(product_id) == 4, "со склада списали дважды"


def test_overlapping_confirmations_take_the_order_once(product_and_order,
                                                       monkeypatch):
    """ГЛАВНАЯ ПРОВЕРКА: наложение, а не последовательность.

    Второй вызов делается ИЗНУТРИ первого — в тот момент, когда первый уже
    решил, что заказ его, но ещё не закончил. Проверка «прочитать и сравнить»
    в этот момент пропускает второго; условный UPDATE — нет.
    """
    product_id, order_id = product_and_order
    inner_result: list = []
    original = shop._take_from_stock

    def take_and_overlap(session, product, quantity):
        # Ровно один раз изображаем второго подтверждающего.
        if not inner_result:
            inner_result.append(shop.mark_crypto_order_paid(order_id))
        return original(session, product, quantity)

    monkeypatch.setattr(shop, "_take_from_stock", take_and_overlap)

    outer = shop.mark_crypto_order_paid(order_id)

    assert outer is not None, "первый вызов должен подтвердить заказ"
    assert inner_result == [None], (
        "наложившееся подтверждение прошло вторым — заказ забрали дважды"
    )
    assert _stock(product_id) == 4, (
        f"со склада списали дважды: остаток {_stock(product_id)} вместо 4"
    )


def test_confirmation_still_marks_oversold_when_stock_ran_out():
    """Обратная проверка: захват заказа не должен потерять пометку «продано
    сверх остатка». Деньги уже пришли, отказать нельзя — но владелец обязан
    увидеть, что отдавать нечего."""
    with session_scope() as session:
        session.query(Order).delete()
        session.query(Product).delete()
        product = Product(name="Последний", price=100.0, currency="RUB",
                          is_active=True, stock=0)
        session.add(product)
        session.flush()
        product_id = product.id

    order = shop.create_crypto_order(
        user_id=78, product_id=product_id, rail_id=1,
        invoice_id="inv-oversold", crypto_amount="1.0", crypto_asset="USDT",
    )

    paid = shop.mark_crypto_order_paid(order.id)

    assert paid is not None
    with session_scope() as session:
        row = session.get(Order, order.id)
        assert row.is_oversold is True, "пометка «сверх остатка» потерялась"
        assert row.status == "paid"
        assert row.paid_at is not None, "время оплаты не проставлено"

    with session_scope() as session:
        session.query(Order).delete()
        session.query(Product).delete()
