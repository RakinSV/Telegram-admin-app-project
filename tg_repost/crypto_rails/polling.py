"""Опрос статуса криптосчёта (F70).

ПОЧЕМУ ОПРОС, А НЕ ВЕБХУК. Вебхук требует публичного адреса, а публичная
поверхность — это пересмотр модели угроз (см. F73/F74). Оплачивать его ради
удобства одного провайдера незачем: опрос решает ту же задачу и не открывает
наружу ничего.

ЗАДАЧА ПЕРЕПЛАНИРУЕТ САМА СЕБЯ. Каждый проход либо подтверждает оплату, либо
ставит следующую проверку через `INTERVAL_SECONDS`. Так опрос переживает
рестарт (очередь лежит в БД) и не превращается в вечный цикл в памяти.

СРОК ЖИЗНИ ЕСТЬ, И ОН РАЗНЫЙ. У посредника счёт истекает сам, и после этого
спрашивать бессмысленно. У прямого перевода на кошелёк истекать нечему:
деньги могут прийти и через сутки, а объявить счёт просроченным значило бы
потерять уже отправленный платёж. Поэтому предел проверок задан числом
попыток, а не «счёт протух».

СБОЙ ПРОВАЙДЕРА — НЕ «НЕ ОПЛАЧЕНО». Ошибка сети роняет задачу, и очередь
повторит её сама; молча считать сбой отсутствием оплаты значит потерять
заказ, за который уже заплатили.
"""

from __future__ import annotations

from datetime import timedelta

from tg_repost import task_queue
from tg_repost.crypto_rails import STATUS_EXPIRED, STATUS_PAID
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

TASK_KIND = "crypto_check"

# Как часто спрашивать. Минута — компромисс: человек ждёт подтверждения и
# смотрит в экран, а провайдеры не любят частых обращений.
INTERVAL_SECONDS = 60
# Сколько всего попыток. Сутки при минутном интервале: дольше ждать перевод,
# который так и не пришёл, незачем, а владелец увидит заказ в списке
# неоплаченных.
MAX_CHECKS = 1440


def schedule(order_id: int, *, delay_seconds: int = INTERVAL_SECONDS) -> int:
    from datetime import datetime, timezone

    return task_queue.enqueue(
        TASK_KIND,
        {"order_id": order_id, "checks": 0},
        run_after=datetime.now(timezone.utc) + timedelta(seconds=delay_seconds),
    )


async def handle_check(view) -> str | None:  # task_queue.TaskView
    """Один проход опроса по одному заказу."""
    from datetime import datetime, timezone

    from tg_repost import crypto_rails_repo, shop_repo

    order_id = int(view.payload["order_id"])
    checks = int(view.payload.get("checks", 0))

    orders = [o for o in shop_repo.pending_crypto_orders() if o.id == order_id]
    if not orders:
        # Заказ оплачен, отменён или удалён, пока задача ждала. Это не сбой:
        # спрашивать больше не о чем.
        return None
    order = orders[0]

    if order.crypto_rail_id is None or not order.crypto_invoice_id:
        logger.warning("F70: заказ #%d без счёта — опрос прекращён", order_id)
        return None

    rail = crypto_rails_repo.build(order.crypto_rail_id)
    # ОЖИДАЕМАЯ СУММА ПЕРЕДАЁТСЯ ОБЯЗАТЕЛЬНО. Прямому переводу без неё
    # сверять нечего: комментарий известен покупателю, и один нанотон с
    # верным комментарием засчитывался бы как полная оплата. Посредники
    # параметр игнорируют — сумму держат они сами.
    status = await rail.check_status(
        order.crypto_invoice_id, expected_amount=order.crypto_amount,
    )

    if status == STATUS_PAID:
        paid = shop_repo.mark_crypto_order_paid(order_id)
        if paid is not None:
            logger.info("F70: оплата заказа #%d подтверждена", order_id)
        return None

    if status == STATUS_EXPIRED:
        logger.info("F70: счёт заказа #%d истёк", order_id)
        return None

    if checks + 1 >= MAX_CHECKS:
        logger.info(
            "F70: заказ #%d не оплачен за %d проверок — опрос прекращён",
            order_id, MAX_CHECKS,
        )
        return None

    task_queue.enqueue(
        TASK_KIND,
        {"order_id": order_id, "checks": checks + 1},
        run_after=datetime.now(timezone.utc) + timedelta(seconds=INTERVAL_SECONDS),
    )
    return None


def register_handler() -> None:
    task_queue.register(TASK_KIND, handle_check)
