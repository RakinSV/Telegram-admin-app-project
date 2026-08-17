"""Сверка суммы в прямом переводе TON (аудит 2026-08-17).

НАЙДЕНА НАСТОЯЩАЯ ДЫРА В ДЕНЬГАХ. Перевод опознавался ТОЛЬКО по
комментарию, а сумма не проверялась вовсе. Комментарий известен покупателю —
он видит его в ссылке на оплату. Значит вместо пятнадцати TON можно было
отправить один нанотон с тем же комментарием и получить товар.

Отдельно стоит того, чтобы это запомнить: и docstring адаптера, и
`FEATURES.md` УТВЕРЖДАЛИ, что сумма сравнивается и недоплата не считается
оплатой. Текст был написан, код — нет. Обещание в комментарии не защищает
ничего; проверку выполняет только код и тест на него.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tg_repost.crypto_rails import STATUS_PAID, STATUS_PENDING, RailError
from tg_repost.crypto_rails.adapters import TonDirectRail

NANO = 1_000_000_000
MEMO = "order-42"


def _answer(*transfers: tuple[str, int]):
    """Ответ индексатора: пары (комментарий, сумма в нанотонах)."""
    response = AsyncMock()
    response.status_code = 200
    response.json = lambda: {
        "ok": True,
        "result": [
            {"in_msg": {"message": memo, "value": str(value)}}
            for memo, value in transfers
        ],
    }
    return response


async def _check(rail: TonDirectRail, transfers, expected: str | None):
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_answer(*transfers))):
        return await rail.check_status(MEMO, expected_amount=expected)


@pytest.fixture
def _rail() -> TonDirectRail:
    return TonDirectRail("EQtest_address")


# --- недоплата ---


async def test_one_nanoton_is_not_a_payment(_rail):
    """ГЛАВНАЯ ДЫРА, ЗАКРЫТАЯ ЭТИМ ТЕСТОМ."""
    status = await _check(_rail, [(MEMO, 1)], "15.0")

    assert status == STATUS_PENDING


async def test_almost_enough_is_not_enough(_rail):
    """На один нанотон меньше — всё ещё недоплата: границу надо держать
    именно там, где она объявлена."""
    status = await _check(_rail, [(MEMO, 15 * NANO - 1)], "15.0")

    assert status == STATUS_PENDING


async def test_exact_amount_is_accepted(_rail):
    status = await _check(_rail, [(MEMO, 15 * NANO)], "15.0")

    assert status == STATUS_PAID


async def test_overpayment_is_accepted(_rail):
    """Сдачу система не возвращает, и делать вид, что платежа не было,
    нельзя — деньги уже на кошельке."""
    status = await _check(_rail, [(MEMO, 20 * NANO)], "15.0")

    assert status == STATUS_PAID


# --- посторонние переводы ---


async def test_someone_elses_transfer_is_ignored(_rail):
    """На кошелёк приходят чужие переводы: комментарий — единственная связь
    платежа с заказом."""
    status = await _check(_rail, [("order-99", 100 * NANO)], "15.0")

    assert status == STATUS_PENDING


async def test_right_memo_among_many_transfers(_rail):
    status = await _check(
        _rail,
        [("order-7", 5 * NANO), (MEMO, 15 * NANO), ("", 1 * NANO)],
        "15.0",
    )

    assert status == STATUS_PAID


async def test_underpaid_does_not_shadow_a_good_one(_rail):
    """Сначала пришла недоплата, потом полная сумма с тем же комментарием —
    заказ оплачен."""
    status = await _check(
        _rail, [(MEMO, 1), (MEMO, 15 * NANO)], "15.0",
    )

    assert status == STATUS_PAID


# --- испорченные данные ---


async def test_unreadable_amount_is_not_a_payment(_rail):
    """Индексатор отдал сумму, которую не прочитать. Это не «оплачено»:
    лучше подождать следующего опроса, чем отдать товар по невнятным
    данным."""
    status = await _check(_rail, [(MEMO, "не число")], "15.0")

    assert status == STATUS_PENDING


async def test_broken_expected_amount_is_an_error_not_a_pass(_rail):
    """Сумма заказа нечитаема — это сбой системы, а не разрешение отдать
    товар."""
    with pytest.raises(RailError):
        await _check(_rail, [(MEMO, 15 * NANO)], "пятнадцать")


# --- перевод в нанотоны ---


@pytest.mark.parametrize(
    "amount,nano",
    [
        ("1", NANO),
        ("1.5", 1_500_000_000),
        ("0.000000001", 1),
        ("0.3", 300_000_000),
        # На девяти знаках float начинает врать: даёт ...784 вместо ...789.
        ("123456789.123456789", 123456789123456789),
    ],
)
def test_conversion_is_exact(amount: str, nano: int):
    assert TonDirectRail._to_nano(amount) == nano


def test_conversion_does_not_use_float():
    """Сравнение сумм не должно зависеть от того, повезло ли с порядком
    величины."""
    import inspect

    source = inspect.getsource(TonDirectRail._to_nano)

    assert "Decimal" in source
    assert "float(" not in source
