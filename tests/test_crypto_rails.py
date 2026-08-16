"""Приём криптовалюты: три способа, привязка к группам (F70).

Проверяется не «HTTP-запрос ушёл», а то, из-за чего владелец теряет деньги:
ключи провайдеров в открытом виде, счёт на чужой кошелёк, недоплата,
засчитанная как оплата, и придуманный курс.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tg_repost import crypto_rails_repo as rails
from tg_repost.crypto_rails import (
    KIND_CRYPTOBOT,
    KIND_TON_DIRECT,
    KIND_WALLETPAY,
    STATUS_PAID,
    STATUS_PENDING,
    RailError,
)
from tg_repost.crypto_rails.adapters import TonDirectRail, build_rail
from tg_repost.db.models import CryptoRail, Product, TargetGroup
from tg_repost.db.session import session_scope

CHAT_A = -100901
CHAT_B = -100902


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(CryptoRail).delete()
            session.query(Product).delete()
            session.query(TargetGroup).delete()

    _wipe()
    yield
    _wipe()


def _group(chat_id: int) -> None:
    with session_scope() as session:
        session.add(TargetGroup(chat_id=chat_id, title=f"Группа {chat_id}"))


def _product(chat_id: int | None = None, currency: str = "RUB") -> int:
    from tg_repost import shop_repo

    product_id = shop_repo.save_product(name="Кружка", price=100000, is_active=True)
    if chat_id is not None or currency != "RUB":
        with session_scope() as session:
            row = session.get(Product, product_id)
            row.chat_id = chat_id
            row.currency = currency
    return product_id


# --- хранение ключей ---


def test_credential_is_never_stored_in_plain_text():
    """ГЛАВНОЕ. Токен CryptoBot — это доступ к деньгам: открытым в базе он
    уезжает вместе с первым же бэкапом."""
    rails.save(name="Касса", kind=KIND_CRYPTOBOT, credential="секретный-токен")

    with session_scope() as session:
        row = session.query(CryptoRail).one()
        assert "секретный-токен" not in row.credential_encrypted


def test_view_has_no_credential_field():
    """Не маскируем, а НЕ КЛАДЁМ: то, чего в объекте нет, невозможно
    случайно вывести в шаблон."""
    rails.save(name="Касса", kind=KIND_CRYPTOBOT, credential="секрет")

    view = rails.list_all()[0]

    assert not hasattr(view, "credential")
    assert "секрет" not in repr(view)


def test_credential_round_trips_into_a_working_rail():
    rail_id = rails.save(name="Касса", kind=KIND_CRYPTOBOT, credential="токен-1")

    adapter = rails.build(rail_id)

    assert adapter.kind == KIND_CRYPTOBOT


def test_empty_credential_on_edit_keeps_the_old_one():
    """Форма не показывает сохранённый ключ; трактовать пустое поле как
    очистку значило бы ломать способ при каждой правке названия."""
    rail_id = rails.save(name="Касса", kind=KIND_CRYPTOBOT, credential="токен-1")

    rails.save(rail_id=rail_id, name="Касса №1", kind=KIND_CRYPTOBOT, credential="")

    assert rails.build(rail_id) is not None
    assert rails.get(rail_id).name == "Касса №1"


def test_new_rail_without_credential_is_refused():
    with pytest.raises(rails.InvalidRail):
        rails.save(name="Пустая", kind=KIND_CRYPTOBOT, credential="")


def test_unknown_kind_is_refused():
    with pytest.raises(rails.InvalidRail):
        rails.save(name="Что-то", kind="монеты", credential="x")


def test_ton_address_is_shown_openly():
    """Адрес не секрет: владелец сверяется по нему с кошельком."""
    rails.save(name="Кошелёк", kind=KIND_TON_DIRECT, credential="EQxxx")

    assert rails.list_all()[0].public_address == "EQxxx"


def test_provider_token_is_not_shown_as_address():
    rails.save(name="Касса", kind=KIND_CRYPTOBOT, credential="токен")

    assert rails.list_all()[0].public_address is None


# --- какой кошелёк для какого товара ---


def test_group_rail_wins_over_default():
    """То, ради чего всё затевалось: в этой группе один кошелёк, в той другой."""
    default_id = rails.save(
        name="Общий", kind=KIND_CRYPTOBOT, credential="t1", is_default=True,
    )
    group_id = rails.save(name="Для группы A", kind=KIND_TON_DIRECT, credential="EQaaa")
    _group(CHAT_A)
    rails.bind_to_group(CHAT_A, group_id)

    chosen = rails.rail_for_product(_product(chat_id=CHAT_A))

    assert chosen is not None
    assert chosen.id == group_id != default_id


def test_product_without_group_uses_the_default():
    default_id = rails.save(
        name="Общий", kind=KIND_CRYPTOBOT, credential="t1", is_default=True,
    )
    rails.save(name="Для группы", kind=KIND_TON_DIRECT, credential="EQaaa")

    chosen = rails.rail_for_product(_product(chat_id=None))

    assert chosen is not None and chosen.id == default_id


def test_group_without_binding_uses_the_default():
    default_id = rails.save(
        name="Общий", kind=KIND_CRYPTOBOT, credential="t1", is_default=True,
    )
    _group(CHAT_B)

    chosen = rails.rail_for_product(_product(chat_id=CHAT_B))

    assert chosen is not None and chosen.id == default_id


def test_disabled_group_rail_falls_back_to_default():
    """Выключенный кошелёк не должен останавливать продажи молча."""
    default_id = rails.save(
        name="Общий", kind=KIND_CRYPTOBOT, credential="t1", is_default=True,
    )
    group_id = rails.save(
        name="Выключенный", kind=KIND_TON_DIRECT, credential="EQaaa", is_active=False,
    )
    _group(CHAT_A)
    rails.bind_to_group(CHAT_A, group_id)

    chosen = rails.rail_for_product(_product(chat_id=CHAT_A))

    assert chosen is not None and chosen.id == default_id


def test_without_any_rail_nothing_is_chosen():
    assert rails.rail_for_product(_product()) is None


def test_only_one_default_survives():
    first = rails.save(
        name="Первый", kind=KIND_CRYPTOBOT, credential="t1", is_default=True,
    )
    rails.save(name="Второй", kind=KIND_WALLETPAY, credential="t2", is_default=True)

    defaults = [r.id for r in rails.list_all() if r.is_default]

    assert len(defaults) == 1
    assert first not in defaults


def test_deleting_a_rail_unbinds_the_group():
    """Группа со ссылкой на удалённый кошелёк выглядела бы настроенной, а
    платить было бы некуда."""
    rail_id = rails.save(name="Кошелёк", kind=KIND_TON_DIRECT, credential="EQaaa")
    _group(CHAT_A)
    rails.bind_to_group(CHAT_A, rail_id)

    rails.delete(rail_id)

    with session_scope() as session:
        row = session.query(TargetGroup).filter(TargetGroup.chat_id == CHAT_A).one()
        assert row.crypto_rail_id is None


def test_binding_a_missing_rail_is_refused():
    _group(CHAT_A)

    assert rails.bind_to_group(CHAT_A, 999999) is False


# --- прямой перевод на TON ---


async def test_ton_invoice_carries_a_memo():
    """Комментарий — единственная связь перевода с заказом: без него на
    кошелёк приходят неотличимые суммы."""
    rail = TonDirectRail("EQtest")

    invoice = await rail.create_invoice(
        amount="1.5", asset="TON", order_id=42, description="Кружка",
    )

    assert "order-42" in invoice.pay_url
    assert invoice.external_id == "order-42"


async def test_ton_invoice_amount_is_in_nanotons():
    rail = TonDirectRail("EQtest")

    invoice = await rail.create_invoice(
        amount="1.5", asset="TON", order_id=1, description="",
    )

    assert "amount=1500000000" in invoice.pay_url


async def test_ton_refuses_fiat_instead_of_inventing_a_rate():
    """КЛЮЧЕВОЕ РЕШЕНИЕ ФИЧИ.

    Курс со стороннего сервиса означал бы: сервис врёт или лежит — владелец
    молча недополучает на каждой продаже и замечает через месяц.
    """
    rail = TonDirectRail("EQtest")

    with pytest.raises(RailError) as exc:
        await rail.create_invoice(
            amount="1000", asset="RUB", order_id=1, description="",
        )

    assert "TON" in str(exc.value)


async def test_ton_payment_is_found_by_memo():
    rail = TonDirectRail("EQtest")
    response = AsyncMock()
    response.status_code = 200
    response.json = lambda: {
        "ok": True,
        "result": [{"in_msg": {"message": "order-7", "value": "2000000000"}}],
    }

    with patch("httpx.AsyncClient.get", AsyncMock(return_value=response)):
        assert await rail.check_status("order-7") == STATUS_PAID


async def test_ton_ignores_other_peoples_transfers():
    rail = TonDirectRail("EQtest")
    response = AsyncMock()
    response.status_code = 200
    response.json = lambda: {
        "ok": True,
        "result": [{"in_msg": {"message": "order-999", "value": "9000000000"}}],
    }

    with patch("httpx.AsyncClient.get", AsyncMock(return_value=response)):
        assert await rail.check_status("order-7") == STATUS_PENDING


def test_underpayment_is_not_enough():
    """Отдать товар за меньшие деньги — та же потеря, что не отдать вовсе."""
    rail = TonDirectRail("EQtest")
    transaction = {"in_msg": {"value": str(int(0.9 * TonDirectRail.NANO))}}

    assert rail.received_enough(transaction, "1.0") is False
    assert rail.received_enough(
        {"in_msg": {"value": str(TonDirectRail.NANO)}}, "1.0",
    ) is True


async def test_indexer_failure_is_not_silence():
    """«Не оплачено» и «не смогли спросить» — разные вещи; вторая обязана
    быть видна как сбой."""
    rail = TonDirectRail("EQtest")
    response = AsyncMock()
    response.status_code = 502

    with patch("httpx.AsyncClient.get", AsyncMock(return_value=response)):
        with pytest.raises(RailError):
            await rail.check_status("order-7")


# --- провайдеры ---


async def test_cryptobot_sends_fiat_amount():
    """Посреднику называем сумму в рублях — пересчёт его забота."""
    rail = build_rail(KIND_CRYPTOBOT, "токен")
    response = AsyncMock()
    response.status_code = 200
    response.json = lambda: {
        "ok": True,
        "result": {"invoice_id": 77, "bot_invoice_url": "https://t.me/pay"},
    }

    with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)) as post:
        invoice = await rail.create_invoice(
            amount="1000.00", asset="RUB", order_id=5, description="Кружка",
        )

    assert invoice.external_id == "77"
    assert post.await_args.kwargs["json"]["currency_type"] == "fiat"
    assert post.await_args.kwargs["json"]["payload"] == "5"


async def test_cryptobot_error_is_raised_not_swallowed():
    rail = build_rail(KIND_CRYPTOBOT, "токен")
    response = AsyncMock()
    response.status_code = 200
    response.json = lambda: {"ok": False, "error": "неверный токен"}

    with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)):
        with pytest.raises(RailError):
            await rail.create_invoice(
                amount="1", asset="RUB", order_id=1, description="",
            )


async def test_walletpay_reports_paid():
    rail = build_rail(KIND_WALLETPAY, "ключ")
    response = AsyncMock()
    response.status_code = 200
    response.json = lambda: {"data": {"status": "PAID"}}

    with patch("httpx.AsyncClient.get", AsyncMock(return_value=response)):
        assert await rail.check_status("order-1") == STATUS_PAID


def test_unknown_kind_cannot_be_built():
    with pytest.raises(RailError):
        build_rail("монеты", "x")
