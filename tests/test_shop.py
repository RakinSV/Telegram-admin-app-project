"""Магазин: товары, заказы, остатки (F69 + F70).

Главное здесь — граница между цифровым и физическим (её задаёт Telegram, и
нарушение стоит бана бота) и поведение склада на грани: что происходит,
когда последний товар оплачивают двое.
"""

from __future__ import annotations

import pytest

from tg_repost import shop_repo as shop
from tg_repost.db.models import Order, Product
from tg_repost.db.session import session_scope

ALICE = 9601
BOB = 9602


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(Order).delete()
            session.query(Product).delete()

    _wipe()
    yield
    _wipe()


def _product(price: int = 100000, stock: int | None = None, active: bool = True) -> int:
    return shop.save_product(
        name="Кружка", price=price, stock=stock, is_active=active,
    )


# --- товары ---


def test_price_is_stored_in_minor_units():
    """Дробные рубли рано или поздно дают 0.30000000000000004, и расхождение
    с эквайрингом ищут неделями."""
    product_id = _product(price=149900)

    view = shop.get_product(product_id)

    assert view is not None
    assert view.price == 149900
    assert view.price_human == "1499.00 RUB"


def test_digital_product_is_refused():
    """ГРАНИЦА, ЗАДАННАЯ TELEGRAM.

    Цифровое за рубли — основание для бана бота, а не спорное решение.
    """
    with pytest.raises(shop.InvalidProduct) as exc:
        shop.save_product(name="Курс", price=100000, is_physical=False)

    assert "Stars" in str(exc.value)


def test_zero_price_is_refused():
    with pytest.raises(shop.InvalidProduct):
        shop.save_product(name="Подарок", price=0)


def test_negative_stock_is_refused():
    with pytest.raises(shop.InvalidProduct):
        shop.save_product(name="Кружка", price=100, stock=-1)


def test_new_product_is_inactive():
    """Товар не должен попадать в продажу в момент создания."""
    product_id = shop.save_product(name="Кружка", price=100000)

    view = shop.get_product(product_id)
    assert view is not None and view.is_active is False


def test_editing_keeps_the_same_product():
    product_id = _product()

    again = shop.save_product(product_id=product_id, name="Кружка XL", price=200000)

    assert again == product_id
    assert len(shop.list_products()) == 1


def test_only_active_products_are_offered():
    _product(active=True)
    shop.save_product(name="Черновик", price=100000, is_active=False)

    assert [p.name for p in shop.list_products(only_active=True)] == ["Кружка"]


# --- продажа ---


def test_active_product_in_stock_can_be_sold():
    product_id = _product(stock=5)

    assert shop.can_sell(product_id) == (True, "")


def test_sold_out_product_cannot_be_sold():
    """Отказ в pre_checkout безболезнен: деньги ещё не ушли."""
    product_id = _product(stock=0)

    ok, reason = shop.can_sell(product_id)

    assert ok is False
    assert "закончился" in reason


def test_inactive_product_cannot_be_sold():
    product_id = _product(active=False)

    assert shop.can_sell(product_id)[0] is False


def test_missing_product_cannot_be_sold():
    assert shop.can_sell(999999)[0] is False


def test_unlimited_stock_never_runs_out():
    product_id = _product(stock=None)
    shop.record_paid_order(
        user_id=ALICE, product_id=product_id, amount=100000,
        currency="RUB", charge_id="c1",
    )

    assert shop.can_sell(product_id)[0] is True


# --- оплата и склад ---


def test_paid_order_decrements_stock():
    product_id = _product(stock=3)

    shop.record_paid_order(
        user_id=ALICE, product_id=product_id, amount=100000,
        currency="RUB", charge_id="c1",
    )

    view = shop.get_product(product_id)
    assert view is not None and view.stock == 2


def test_repeated_payment_update_creates_one_order():
    """Повторная доставка апдейта не должна порождать вторую посылку."""
    product_id = _product(stock=3)

    first = shop.record_paid_order(
        user_id=ALICE, product_id=product_id, amount=100000,
        currency="RUB", charge_id="c1",
    )
    second = shop.record_paid_order(
        user_id=ALICE, product_id=product_id, amount=100000,
        currency="RUB", charge_id="c1",
    )

    assert first is not None
    assert second is None
    assert len(shop.list_orders()) == 1
    assert shop.get_product(product_id).stock == 2


def test_duplicate_order_is_stopped_by_the_database():
    """ВТОРАЯ ЛИНИЯ ЗАЩИТЫ, найдена аудитом 2026-08-16.

    Проверки в коде мало: между ней и вставкой помещается вторая доставка
    того же апдейта. В платёжном журнале F49 ограничение стояло с самого
    начала, а в заказах его не было — покупатель мог получить две посылки
    за одни деньги. Здесь проверяется именно ограничение БАЗЫ: строка
    добавляется в обход репозитория.
    """
    from sqlalchemy.exc import IntegrityError

    from tg_repost.db.models import Order

    product_id = _product()
    shop.record_paid_order(
        user_id=ALICE, product_id=product_id, amount=100000,
        currency="RUB", charge_id="dup",
    )

    with pytest.raises(IntegrityError):
        with session_scope() as session:
            session.add(Order(
                user_id=BOB, product_id=product_id, product_name="Кружка",
                amount=100000, currency="RUB", status=shop.STATUS_PAID,
                charge_id="dup",
            ))


def test_orders_without_payment_do_not_collide():
    """Заказов без платежа может быть много: уникальность на NULL в SQL не
    срабатывает, и здесь это ровно то, что нужно."""
    from tg_repost.db.models import Order

    product_id = _product()
    with session_scope() as session:
        for user in (ALICE, BOB):
            session.add(Order(
                user_id=user, product_id=product_id, product_name="Кружка",
                amount=100000, currency="RUB", status=shop.STATUS_NEW,
            ))

    assert len(shop.list_orders()) == 2


def test_last_item_paid_twice_is_accepted_and_flagged():
    """ГЛАВНАЯ ГРАНИЦА СКЛАДА.

    Двое оплатили последний товар одновременно. Отказать ПОСЛЕ оплаты
    нельзя, а молча потерять один заказ — значит дать человеку узнать об
    этом самому, когда посылка не придёт.
    """
    product_id = _product(stock=1)

    shop.record_paid_order(
        user_id=ALICE, product_id=product_id, amount=100000,
        currency="RUB", charge_id="c1",
    )
    second = shop.record_paid_order(
        user_id=BOB, product_id=product_id, amount=100000,
        currency="RUB", charge_id="c2",
    )

    assert second is not None
    assert second.is_oversold is True
    assert shop.get_product(product_id).stock == 0


def test_order_keeps_price_when_product_changes():
    """Товар подорожает, а в заказе должна остаться сумма, по которой
    человек платил."""
    product_id = _product(price=100000)
    shop.record_paid_order(
        user_id=ALICE, product_id=product_id, amount=100000,
        currency="RUB", charge_id="c1",
    )

    shop.save_product(product_id=product_id, name="Кружка", price=500000)

    assert shop.list_orders()[0].amount == 100000


def test_product_with_orders_is_hidden_instead_of_deleted():
    """НАЙДЕНО АУДИТОМ 2026-08-16.

    Раньше товар удалялся, и в заказах оставалась ссылка в никуда. На SQLite
    это проходило молча (`PRAGMA foreign_keys` = 0), а на Postgres, куда
    проект собирается переезжать, тот же вызов упал бы нарушением внешнего
    ключа — ошибка ждала переезда.
    """
    product_id = _product()
    shop.record_paid_order(
        user_id=ALICE, product_id=product_id, amount=100000,
        currency="RUB", charge_id="c1",
    )

    assert shop.delete_product(product_id) is False

    view = shop.get_product(product_id)
    assert view is not None, "товар с заказами не должен исчезать"
    assert view.is_active is False, "но из продажи он снимается"
    assert shop.list_orders()[0].product_name == "Кружка"


def test_product_without_orders_is_deleted():
    """Ошибочно заведённый товар удалить всё же можно."""
    product_id = _product()

    assert shop.delete_product(product_id) is True
    assert shop.get_product(product_id) is None


# --- статусы и выручка ---


def test_shipped_order_cannot_go_back_to_paid():
    """Статус, отрицающий уже случившееся, врёт и человеку, и отчётности."""
    product_id = _product()
    order = shop.record_paid_order(
        user_id=ALICE, product_id=product_id, amount=100000,
        currency="RUB", charge_id="c1",
    )
    shop.set_order_status(order.id, shop.STATUS_SHIPPED)

    assert shop.set_order_status(order.id, shop.STATUS_PAID) is False


def test_canceled_order_cannot_be_revived():
    """НАЙДЕНО АУДИТОМ 2026-08-16.

    За отменой обычно стоит возврат денег. Воскресший заказ означал бы, что
    мы обещаем товар за деньги, которые вернули; нужен новый заказ.
    """
    product_id = _product()
    order = shop.record_paid_order(
        user_id=ALICE, product_id=product_id, amount=100000,
        currency="RUB", charge_id="c1",
    )
    shop.set_order_status(order.id, shop.STATUS_CANCELED)

    assert shop.set_order_status(order.id, shop.STATUS_PAID) is False
    assert shop.set_order_status(order.id, shop.STATUS_SHIPPED) is False
    assert shop.list_orders()[0].status == shop.STATUS_CANCELED


def test_repeating_the_same_status_is_harmless():
    """Двойной клик по «Отправлен» не должен выглядеть ошибкой."""
    product_id = _product()
    order = shop.record_paid_order(
        user_id=ALICE, product_id=product_id, amount=100000,
        currency="RUB", charge_id="c1",
    )
    shop.set_order_status(order.id, shop.STATUS_SHIPPED)

    assert shop.set_order_status(order.id, shop.STATUS_SHIPPED) is True


def test_unknown_status_is_refused():
    product_id = _product()
    order = shop.record_paid_order(
        user_id=ALICE, product_id=product_id, amount=100000,
        currency="RUB", charge_id="c1",
    )

    assert shop.set_order_status(order.id, "потерян") is False


def test_revenue_ignores_canceled_orders():
    product_id = _product()
    first = shop.record_paid_order(
        user_id=ALICE, product_id=product_id, amount=100000,
        currency="RUB", charge_id="c1",
    )
    shop.record_paid_order(
        user_id=BOB, product_id=product_id, amount=250000,
        currency="RUB", charge_id="c2",
    )
    shop.set_order_status(first.id, shop.STATUS_CANCELED)

    assert shop.revenue() == 250000


# --- payload ---


def test_payload_roundtrip():
    assert shop.parse_payload(shop.build_payload(42)) == 42


@pytest.mark.parametrize("raw", [None, "", "ord:", "ord:abc", "sub:1", "мусор"])
def test_broken_payload_is_rejected(raw):
    assert shop.parse_payload(raw) is None


def test_shop_and_subscription_payloads_do_not_collide():
    """Один обработчик оплаты разбирает оба вида счетов — перепутать их
    значило бы выдать доступ в канал за оплату кружки."""
    from engage.handlers import subscription

    assert subscription.parse_payload(shop.build_payload(1)) is None
    assert shop.parse_payload(subscription.build_payload(1)) is None
