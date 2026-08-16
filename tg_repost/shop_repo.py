"""Магазин в боте: товары, заказы, оплата (F69 + F70).

ГРАНИЦА С F49 ЗАДАНА НЕ НАМИ. Цифровое, потребляемое внутри Telegram, —
только Stars; обход ведёт к бану бота. Физические товары и реальные услуги —
обычный эквайринг через Bot Payments API с провайдером из @BotFather.
Поэтому магазин и подписка не сливаются в один «платёжный модуль»: у них
разные правила, разные валюты и разные последствия ошибки.

ЦЕНА ЦЕЛЫМ ЧИСЛОМ В КОПЕЙКАХ. Так требует Bot Payments API, и так же не
возникает классической ошибки денег: дробные рубли рано или поздно дают
0.1 + 0.2 = 0.30000000000000004, а расхождение с эквайрингом ищут неделями.

ОСТАТОК СПИСЫВАЕТСЯ ПРИ ОПЛАТЕ, А НЕ ПРИ ОТКРЫТИИ СЧЁТА. Иначе брошенные
корзины съедают склад: человек нажал «купить», передумал, а товар числится
занятым. Цена такого выбора — возможность продать последний экземпляр
дважды, если двое платят одновременно. Отказать ПОСЛЕ оплаты нельзя, поэтому
заказ принимается и помечается `is_oversold`: владелец увидит и решит,
вернуть деньги или довезти. Молча потерять один из двух заказов было бы
хуже — второй покупатель узнал бы об этом сам, когда посылка не пришла.

ПРОВЕРКА ОСТАТКА ЖИВЁТ В `pre_checkout`. Это единственный момент, когда
Telegram спрашивает нас перед списанием денег, и отказ там для человека
безболезнен — деньги не ушли.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from tg_repost.db.models import Order, Product
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

STATUS_NEW = "new"
STATUS_PAID = "paid"
STATUS_SHIPPED = "shipped"
STATUS_CANCELED = "canceled"

PAYLOAD_PREFIX = "ord"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InvalidProduct(ValueError):
    """Товар не прошёл проверку."""


@dataclass(frozen=True)
class ProductView:
    id: int
    name: str
    description: str | None
    price: int
    currency: str
    stock: int | None
    is_active: bool
    is_physical: bool

    @property
    def in_stock(self) -> bool:
        return self.stock is None or self.stock > 0

    @property
    def price_human(self) -> str:
        """Цена для показа человеку: копейки обратно в рубли."""
        return f"{self.price / 100:.2f} {self.currency}"


@dataclass(frozen=True)
class OrderView:
    id: int
    user_id: int
    product_id: int
    product_name: str
    quantity: int
    amount: int
    currency: str
    status: str
    shipping: str | None
    is_oversold: bool
    created_at: datetime
    paid_at: datetime | None

    @property
    def amount_human(self) -> str:
        return f"{self.amount / 100:.2f} {self.currency}"


def _product_view(row: Product) -> ProductView:
    return ProductView(
        id=row.id, name=row.name, description=row.description, price=row.price,
        currency=row.currency, stock=row.stock, is_active=row.is_active,
        is_physical=row.is_physical,
    )


def _order_view(row: Order) -> OrderView:
    return OrderView(
        id=row.id, user_id=row.user_id, product_id=row.product_id,
        product_name=row.product_name, quantity=row.quantity, amount=row.amount,
        currency=row.currency, status=row.status, shipping=row.shipping,
        is_oversold=row.is_oversold, created_at=row.created_at, paid_at=row.paid_at,
    )


# --- товары ---


def save_product(
    *,
    product_id: int | None = None,
    name: str,
    price: int,
    description: str | None = None,
    currency: str = "RUB",
    stock: int | None = None,
    is_physical: bool = True,
    is_active: bool = False,
) -> int:
    """Создать или обновить товар. Цена — в копейках."""
    clean_name = name.strip()
    if not clean_name:
        raise InvalidProduct("Название не может быть пустым")
    if price <= 0:
        # Бесплатный «товар» через эквайринг не проходит вовсе, а нулевая
        # цена в каталоге читается как ошибка ввода.
        raise InvalidProduct("Цена должна быть больше нуля")
    if stock is not None and stock < 0:
        raise InvalidProduct("Остаток не может быть отрицательным")
    if not is_physical:
        # Не запрет ради запрета: цифровой товар за рубли — это основание
        # для бана бота, а не спорное решение.
        raise InvalidProduct(
            "Цифровые товары продаются только за Stars (F49) — иначе бан бота"
        )

    with session_scope() as session:
        row = session.get(Product, product_id) if product_id is not None else None
        if row is None:
            row = Product(name=clean_name)
            session.add(row)
        row.name = clean_name
        row.description = (description or "").strip() or None
        row.price = price
        row.currency = currency
        row.stock = stock
        row.is_physical = True
        row.is_active = is_active
        session.flush()
        return row.id


def get_product(product_id: int) -> ProductView | None:
    with session_scope() as session:
        row = session.get(Product, product_id)
        return _product_view(row) if row is not None else None


def list_products(*, only_active: bool = False) -> list[ProductView]:
    with session_scope() as session:
        query = session.query(Product)
        if only_active:
            query = query.filter(Product.is_active.is_(True))
        rows = query.order_by(Product.name.asc()).all()
        return [_product_view(row) for row in rows]


def set_active(product_id: int, active: bool) -> bool:
    with session_scope() as session:
        row = session.get(Product, product_id)
        if row is None:
            return False
        row.is_active = active
        return True


def delete_product(product_id: int) -> bool:
    """Удалить товар. Заказы на него остаются — в них своя копия названия.

    Именно поэтому название и сумма копируются в заказ: удаление товара не
    должно стирать историю покупок человека.
    """
    with session_scope() as session:
        row = session.get(Product, product_id)
        if row is None:
            return False
        session.delete(row)
        return True


# --- заказы ---


def build_payload(product_id: int) -> str:
    return f"{PAYLOAD_PREFIX}:{product_id}"


def parse_payload(payload: str | None) -> int | None:
    if not payload or not payload.startswith(PAYLOAD_PREFIX + ":"):
        return None
    try:
        return int(payload.split(":", 1)[1])
    except ValueError:
        return None


def can_sell(product_id: int) -> tuple[bool, str]:
    """Можно ли сейчас продать. Вызывается из `pre_checkout`.

    Единственный момент, когда Telegram спрашивает нас ДО списания денег, —
    отказ здесь для человека безболезнен.
    """
    view = get_product(product_id)
    if view is None:
        return False, "Товар больше не продаётся."
    if not view.is_active:
        return False, "Товар снят с продажи."
    if not view.in_stock:
        return False, "Товар закончился."
    return True, ""


def record_paid_order(
    *,
    user_id: int,
    product_id: int,
    amount: int,
    currency: str,
    charge_id: str,
    shipping: str | None = None,
    quantity: int = 1,
) -> OrderView | None:
    """Создать оплаченный заказ и списать остаток.

    `None` — заказ с таким `charge_id` уже есть: повторная доставка апдейта
    не должна порождать вторую посылку.
    """
    with session_scope() as session:
        existing = (
            session.query(Order).filter(Order.charge_id == charge_id).first()
        )
        if existing is not None:
            logger.info("F69: повторный апдейт об оплате заказа %s", charge_id)
            return None

        product = session.get(Product, product_id)
        name = product.name if product is not None else "Товар удалён"

        oversold = False
        if product is not None and product.stock is not None:
            if product.stock >= quantity:
                product.stock -= quantity
            else:
                # Отказать после оплаты нельзя — принимаем и помечаем.
                product.stock = 0
                oversold = True
                logger.warning(
                    "F69: заказ %s принят сверх остатка товара #%s",
                    charge_id, product_id,
                )

        row = Order(
            user_id=user_id,
            product_id=product_id,
            product_name=name,
            quantity=quantity,
            amount=amount,
            currency=currency,
            status=STATUS_PAID,
            charge_id=charge_id,
            shipping=shipping,
            is_oversold=oversold,
            paid_at=_utcnow(),
        )
        session.add(row)
        session.flush()
        logger.info(
            "F69: заказ #%d оплачен: %s x%d на %d %s",
            row.id, name, quantity, amount, currency,
        )
        return _order_view(row)


def list_orders(status: str | None = None, user_id: int | None = None) -> list[OrderView]:
    with session_scope() as session:
        query = session.query(Order)
        if status is not None:
            query = query.filter(Order.status == status)
        if user_id is not None:
            query = query.filter(Order.user_id == user_id)
        rows = query.order_by(Order.created_at.desc(), Order.id.desc()).all()
        return [_order_view(row) for row in rows]


def set_order_status(order_id: int, status: str) -> bool:
    """Перевести заказ в новый статус.

    Оплаченный заказ нельзя вернуть в «новый»: деньги получены, и статус,
    который это отрицает, врёт и человеку, и отчётности.
    """
    if status not in (STATUS_PAID, STATUS_SHIPPED, STATUS_CANCELED):
        return False
    with session_scope() as session:
        row = session.get(Order, order_id)
        if row is None:
            return False
        if row.status == STATUS_SHIPPED and status == STATUS_PAID:
            return False
        row.status = status
        return True


def revenue(currency: str = "RUB") -> int:
    """Выручка магазина в минимальных единицах. Отменённые не считаются."""
    with session_scope() as session:
        rows = (
            session.query(Order)
            .filter(
                Order.currency == currency,
                Order.status.in_((STATUS_PAID, STATUS_SHIPPED)),
            )
            .all()
        )
        return sum(row.amount for row in rows)
