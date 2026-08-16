"""Три способа приёма крипты за одним интерфейсом (F70).

⚠️ НЕ ПРОВЕРЕНО НА ЖИВЫХ ДЕНЬГАХ. Ни один из трёх адаптеров не вызывался
против настоящего сервиса: для этого нужны аккаунт у провайдера, его токен и
реальная транзакция. Формы запросов взяты из документации, а не подтверждены
опытом. Перед боевым включением каждый способ надо прогнать на копеечной
сумме — и это записано в FEATURES.md отдельным пунктом.

ОБЩИЙ ИНТЕРФЕЙС — ДВЕ ОПЕРАЦИИ. Выставить счёт и спросить, оплачен ли.
Больше ничего от провайдера не нужно: возвраты в крипте невозможны в
принципе (транзакцию не отозвать), а история и так лежит у нас в заказах.

СЕТЕВЫЕ СБОИ НЕ ГЛОТАЮТСЯ. Провайдер, ответивший ошибкой, — это не
«не оплачено»: разница между «денег нет» и «мы не смогли спросить»
принципиальна, и вторая обязана быть видна как сбой, иначе оплаченный заказ
тихо провисит до истечения срока.
"""

from __future__ import annotations

from typing import Protocol

import httpx

from tg_repost.crypto_rails import (
    KIND_CRYPTOBOT,
    KIND_TON_DIRECT,
    KIND_WALLETPAY,
    STATUS_EXPIRED,
    STATUS_PAID,
    STATUS_PENDING,
    CryptoInvoice,
    RailError,
)
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

TIMEOUT = 15.0

CRYPTOBOT_API = "https://pay.crypt.bot/api"
WALLETPAY_API = "https://pay.wallet.tg/wpay/store-api/v1"
# Публичный индексатор TON. Только ЧТЕНИЕ входящих транзакций — ключей от
# кошелька система не держит и держать не должна: приём денег не требует
# права ими распоряжаться.
TONCENTER_API = "https://toncenter.com/api/v2"


class Rail(Protocol):
    kind: str

    async def create_invoice(
        self, *, amount: str, asset: str, order_id: int, description: str,
    ) -> CryptoInvoice: ...

    async def check_status(self, external_id: str) -> str: ...


class CryptoBotRail:
    """Crypto Pay API (@CryptoBot).

    Принимает сумму в фиате: `currency_type=fiat` плюс список валют, которыми
    разрешено платить. Пересчёт — на стороне провайдера.
    """

    kind = KIND_CRYPTOBOT

    def __init__(self, token: str) -> None:
        self._token = token

    async def _call(self, method: str, payload: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(
                f"{CRYPTOBOT_API}/{method}",
                json=payload or {},
                headers={"Crypto-Pay-API-Token": self._token},
            )
        if response.status_code >= 400:
            raise RailError(f"CryptoBot ответил {response.status_code}")
        body = response.json()
        if not body.get("ok"):
            raise RailError(f"CryptoBot: {body.get('error')}")
        return body.get("result") or {}

    async def create_invoice(
        self, *, amount: str, asset: str, order_id: int, description: str,
    ) -> CryptoInvoice:
        result = await self._call("createInvoice", {
            "currency_type": "fiat",
            "fiat": asset,
            "amount": amount,
            "description": description[:1024],
            # Свой идентификатор кладём в payload: по нему заказ находится,
            # даже если ответ провайдера потерялся по дороге.
            "payload": str(order_id),
            "allow_comments": False,
        })
        invoice_id = result.get("invoice_id")
        pay_url = result.get("bot_invoice_url") or result.get("pay_url")
        if not invoice_id or not pay_url:
            raise RailError("CryptoBot не вернул счёт")
        return CryptoInvoice(
            external_id=str(invoice_id), pay_url=pay_url, amount=amount, asset=asset,
        )

    async def check_status(self, external_id: str) -> str:
        result = await self._call("getInvoices", {"invoice_ids": external_id})
        items = result.get("items") or []
        if not items:
            raise RailError("CryptoBot не знает такого счёта")
        status = items[0].get("status")
        if status == "paid":
            return STATUS_PAID
        if status == "expired":
            return STATUS_EXPIRED
        return STATUS_PENDING


class WalletPayRail:
    """Wallet Pay — приём через кошелёк Telegram.

    Тоже работает с фиатной суммой; пересчёт на его стороне.
    """

    kind = KIND_WALLETPAY

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def create_invoice(
        self, *, amount: str, asset: str, order_id: int, description: str,
    ) -> CryptoInvoice:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(
                f"{WALLETPAY_API}/order",
                json={
                    "amount": {"currencyCode": asset, "amount": amount},
                    "description": description[:100],
                    "externalId": str(order_id),
                    "timeoutSeconds": 3600,
                    "customerTelegramUserId": 0,
                },
                headers={"Wpay-Store-Api-Key": self._api_key},
            )
        if response.status_code >= 400:
            raise RailError(f"Wallet Pay ответил {response.status_code}")
        body = response.json()
        data = body.get("data") or {}
        external_id = data.get("id")
        pay_url = data.get("payLink") or data.get("directPayLink")
        if not external_id or not pay_url:
            raise RailError(f"Wallet Pay не вернул счёт: {body.get('message')}")
        return CryptoInvoice(
            external_id=str(external_id), pay_url=pay_url, amount=amount, asset=asset,
        )

    async def check_status(self, external_id: str) -> str:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(
                f"{WALLETPAY_API}/order/preview",
                params={"id": external_id},
                headers={"Wpay-Store-Api-Key": self._api_key},
            )
        if response.status_code >= 400:
            raise RailError(f"Wallet Pay ответил {response.status_code}")
        status = ((response.json().get("data") or {}).get("status") or "").upper()
        if status == "PAID":
            return STATUS_PAID
        if status in ("EXPIRED", "CANCELLED"):
            return STATUS_EXPIRED
        return STATUS_PENDING


class TonDirectRail:
    """Перевод прямо на TON-кошелёк, без посредника.

    ПОСРЕДНИКА НЕТ — ЗНАЧИТ НЕТ И СЧЁТА. «Счёт» здесь это ссылка `ton://` с
    суммой и КОММЕНТАРИЕМ, по которому платёж потом опознаётся. Комментарий —
    единственная связь между переводом и заказом: без него на кошелёк
    приходят неотличимые друг от друга суммы.

    ПРОВЕРКА — ЧТЕНИЕМ БЛОКЧЕЙНА. Смотрим входящие транзакции кошелька и
    ищем свой комментарий. Ключей от кошелька система не имеет: приём денег
    не требует права ими распоряжаться, а лишний секрет — лишний риск.

    СУММА СРАВНИВАЕТСЯ С ЗАПРОШЕННОЙ, и недоплата не считается оплатой.
    Человек может отправить меньше — случайно или намеренно; засчитать такой
    перевод значит отдать товар дешевле, чем он стоит.
    """

    kind = KIND_TON_DIRECT
    # Нанотоны: в блокчейне суммы целые, 1 TON = 10^9.
    NANO = 1_000_000_000

    def __init__(self, address: str) -> None:
        self._address = address

    @staticmethod
    def memo_for(order_id: int) -> str:
        return f"order-{order_id}"

    async def create_invoice(
        self, *, amount: str, asset: str, order_id: int, description: str,
    ) -> CryptoInvoice:
        del description
        if asset != "TON":
            # См. docstring пакета: курс мы не считаем и не тянем.
            raise RailError(
                "Прямой перевод принимает только TON: пересчитывать некому, "
                "а курс со стороннего сервиса означал бы тихую недоплату"
            )
        nano = int(round(float(amount) * self.NANO))
        memo = self.memo_for(order_id)
        return CryptoInvoice(
            external_id=memo,
            pay_url=f"ton://transfer/{self._address}?amount={nano}&text={memo}",
            amount=amount,
            asset="TON",
        )

    async def check_status(self, external_id: str) -> str:
        """Ищем среди входящих перевод с нашим комментарием.

        Возвращает `pending`, пока перевода нет: истечь такой «счёт» не
        может — деньги могут прийти и через сутки, а объявить его
        просроченным значило бы потерять уже отправленный платёж.
        """
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(
                f"{TONCENTER_API}/getTransactions",
                params={"address": self._address, "limit": 50, "archival": "false"},
            )
        if response.status_code >= 400:
            raise RailError(f"TON-индексатор ответил {response.status_code}")
        body = response.json()
        if not body.get("ok"):
            raise RailError("TON-индексатор ответил ошибкой")

        for tx in body.get("result") or []:
            incoming = tx.get("in_msg") or {}
            if (incoming.get("message") or "").strip() != external_id:
                continue
            return STATUS_PAID
        return STATUS_PENDING

    def received_enough(self, transaction: dict, expected_ton: str) -> bool:
        """Хватает ли суммы в найденной транзакции.

        Отдельным методом, потому что недоплату надо уметь показать
        владельцу, а не просто не засчитать.
        """
        value = int((transaction.get("in_msg") or {}).get("value") or 0)
        return value >= int(round(float(expected_ton) * self.NANO))


def build_rail(kind: str, credential: str) -> Rail:
    if kind == KIND_CRYPTOBOT:
        return CryptoBotRail(credential)
    if kind == KIND_WALLETPAY:
        return WalletPayRail(credential)
    if kind == KIND_TON_DIRECT:
        return TonDirectRail(credential)
    raise RailError(f"Неизвестный способ приёма: {kind}")
