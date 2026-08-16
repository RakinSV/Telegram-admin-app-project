"""Оплата криптой из бота: счёт, ожидание, подтверждение (F70).

Крипта устроена НАОБОРОТ по сравнению с картой: там заказ рождается уже
оплаченным (Telegram сообщает о списании), здесь сначала выставляется счёт,
а деньги приходят когда придут — или не приходят вовсе. Отсюда и предмет
тестов: что склад не занимается брошенными счетами, что опрос не теряет
оплату и что сбой провайдера не выглядит как «не оплачено».
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from tg_repost import crypto_rails_repo as rails
from tg_repost import shop_repo as shop
from tg_repost import task_queue
from tg_repost.crypto_rails import STATUS_EXPIRED, STATUS_PAID, STATUS_PENDING, RailError
from tg_repost.crypto_rails import polling
from tg_repost.db.models import CryptoRail, Order, Product, QueuedTask
from tg_repost.db.session import session_scope

ALICE = 9801


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(Order).delete()
            session.query(Product).delete()
            session.query(CryptoRail).delete()
            session.query(QueuedTask).delete()
        task_queue._handlers.clear()

    _wipe()
    yield
    _wipe()


@pytest.fixture
def _rail() -> int:
    return rails.save(
        name="Кошелёк", kind="ton_direct", credential="EQtest", is_default=True,
    )


def _product(stock: int | None = None) -> int:
    return shop.save_product(
        name="Кружка", price=100000, stock=stock, is_active=True,
    )


def _order(rail_id: int, product_id: int, invoice: str = "order-1") -> int:
    view = shop.create_crypto_order(
        user_id=ALICE, product_id=product_id, rail_id=rail_id,
        invoice_id=invoice, crypto_amount="1.5", crypto_asset="TON",
    )
    assert view is not None
    return view.id


def _rail_returning(status: str):
    rail = AsyncMock()
    rail.check_status = AsyncMock(return_value=status)
    return rail


# --- выставление счёта ---


def test_pending_order_does_not_touch_stock(_rail):
    """ГЛАВНОЕ ПРАВИЛО СКЛАДА.

    Списать при выставлении счёта значило бы отдать склад брошенным
    корзинам: нажал «оплатить криптой», передумал — товар занят.
    """
    product_id = _product(stock=3)

    _order(_rail, product_id)

    assert shop.get_product(product_id).stock == 3


def test_pending_order_is_not_counted_as_revenue(_rail):
    product_id = _product()
    _order(_rail, product_id)

    assert shop.revenue() == 0


def test_order_remembers_which_wallet(_rail):
    """Владелец может переназначить кошелёк группы, пока счёт висит; деньги
    придут туда, куда человеку показали ссылку."""
    product_id = _product()
    order_id = _order(_rail, product_id)

    order = shop.list_orders()[0]
    assert order.id == order_id
    assert order.crypto_rail_id == _rail
    assert order.crypto_asset == "TON"


def test_order_for_missing_product_is_not_created(_rail):
    assert shop.create_crypto_order(
        user_id=ALICE, product_id=999999, rail_id=_rail,
        invoice_id="x", crypto_amount="1", crypto_asset="TON",
    ) is None


# --- подтверждение оплаты ---


def test_paid_order_takes_stock(_rail):
    product_id = _product(stock=3)
    order_id = _order(_rail, product_id)

    shop.mark_crypto_order_paid(order_id)

    assert shop.get_product(product_id).stock == 2
    assert shop.revenue() == 100000


def test_confirming_twice_takes_stock_once(_rail):
    """Опрос идёт по расписанию и может наложиться сам на себя."""
    product_id = _product(stock=3)
    order_id = _order(_rail, product_id)

    shop.mark_crypto_order_paid(order_id)
    second = shop.mark_crypto_order_paid(order_id)

    assert second is None
    assert shop.get_product(product_id).stock == 2


def test_sold_out_while_waiting_is_accepted_and_flagged(_rail):
    """Деньги уже пришли — отказать нельзя, но и молчать нельзя."""
    product_id = _product(stock=1)
    first = _order(_rail, product_id, invoice="order-1")
    second = _order(_rail, product_id, invoice="order-2")

    shop.mark_crypto_order_paid(first)
    shop.mark_crypto_order_paid(second)

    orders = {o.id: o for o in shop.list_orders()}
    assert orders[second].is_oversold is True


# --- опрос ---


async def test_polling_confirms_payment(_rail):
    product_id = _product()
    order_id = _order(_rail, product_id)
    polling.register_handler()
    polling.schedule(order_id, delay_seconds=0)

    with patch.object(rails, "build", lambda _id: _rail_returning(STATUS_PAID)):
        await task_queue.run_pending()

    assert shop.list_orders()[0].status == shop.STATUS_PAID


async def test_polling_reschedules_itself_while_pending(_rail):
    """Опрос переживает рестарт: следующая проверка лежит в очереди, а не в
    памяти процесса."""
    product_id = _product()
    order_id = _order(_rail, product_id)
    polling.register_handler()
    polling.schedule(order_id, delay_seconds=0)

    with patch.object(rails, "build", lambda _id: _rail_returning(STATUS_PENDING)):
        await task_queue.run_pending()

    with session_scope() as session:
        pending = session.query(QueuedTask).filter(
            QueuedTask.kind == polling.TASK_KIND,
            QueuedTask.status != "done",
        ).count()
    assert pending == 1
    assert shop.list_orders()[0].status == shop.STATUS_NEW


async def test_expired_invoice_stops_polling(_rail):
    product_id = _product()
    order_id = _order(_rail, product_id)
    polling.register_handler()
    polling.schedule(order_id, delay_seconds=0)

    with patch.object(rails, "build", lambda _id: _rail_returning(STATUS_EXPIRED)):
        await task_queue.run_pending()

    with session_scope() as session:
        waiting = session.query(QueuedTask).filter(
            QueuedTask.kind == polling.TASK_KIND,
            QueuedTask.status != "done",
        ).count()
    assert waiting == 0
    assert shop.list_orders()[0].status == shop.STATUS_NEW


async def test_provider_failure_is_not_treated_as_unpaid(_rail):
    """САМАЯ ОПАСНАЯ ПОДМЕНА.

    «Не смогли спросить» — не «не оплачено». Проглотить сбой значит потерять
    заказ, за который уже заплатили.
    """
    product_id = _product()
    order_id = _order(_rail, product_id)
    polling.register_handler()
    polling.schedule(order_id, delay_seconds=0)

    broken = AsyncMock()
    broken.check_status = AsyncMock(side_effect=RailError("сервис недоступен"))
    with patch.object(rails, "build", lambda _id: broken):
        await task_queue.run_pending()

    assert shop.list_orders()[0].status == shop.STATUS_NEW
    with session_scope() as session:
        task = session.query(QueuedTask).filter(
            QueuedTask.kind == polling.TASK_KIND,
        ).one()
        assert task.last_error is not None


async def test_polling_stops_for_a_paid_order(_rail):
    """Заказ подтвердили другим путём, пока задача ждала."""
    product_id = _product()
    order_id = _order(_rail, product_id)
    shop.mark_crypto_order_paid(order_id)
    polling.register_handler()
    polling.schedule(order_id, delay_seconds=0)

    asked = AsyncMock()
    with patch.object(rails, "build", lambda _id: asked):
        await task_queue.run_pending()

    assert asked.check_status.await_count == 0


# --- кнопка в боте ---


async def test_bot_offers_both_methods_when_both_configured(_rail, monkeypatch):
    """Выбирать за человека нельзя: у карты и крипты разные комиссии и
    скорость, и это его деньги."""
    from engage.handlers import shop as shop_handler

    monkeypatch.setattr(shop_handler, "_enabled", lambda: True)
    monkeypatch.setattr(shop_handler, "_provider_token", lambda: "card-token")
    product_id = _product()

    callback = AsyncMock()
    callback.data = f"buy:{product_id}"
    callback.from_user = SimpleNamespace(id=ALICE)
    await shop_handler.on_buy(callback, AsyncMock())

    markup = callback.message.answer.await_args.kwargs["reply_markup"]
    labels = [b.text for row in markup.inline_keyboard for b in row]
    assert labels == ["Картой", "Криптой"]


async def test_bot_creates_order_only_after_the_invoice(_rail, monkeypatch):
    """Заказ без счёта — строка, которую никто не оплатит: она будет висеть
    в неоплаченных, изображая потерянную продажу."""
    from engage.handlers import shop as shop_handler

    monkeypatch.setattr(shop_handler, "_enabled", lambda: True)
    product_id = _product()

    broken = AsyncMock()
    broken.create_invoice = AsyncMock(side_effect=RailError("провайдер лёг"))
    callback = AsyncMock()
    callback.data = f"pay:crypto:{product_id}"
    callback.from_user = SimpleNamespace(id=ALICE)

    with patch.object(rails, "build", lambda _id: broken):
        await shop_handler.on_pay_crypto(callback)

    assert shop.list_orders() == []
