"""Исходящие вебхуки: события системы наружу (F73).

ИСХОДЯЩИЕ, А НЕ ВХОДЯЩИЕ. Мы шлём POST в чужую систему; принимать чужие
вызовы система не умеет намеренно — это была бы третья публичная поверхность
со своей аутентификацией, а исходящие закрывают исходную задачу (связь с 1С
и CRM) без неё.

ПОДПИСЬ ОБЯЗАТЕЛЬНА. Получатель иначе не отличит наш вызов от чужого,
знающего адрес, — а адрес утечёт первым же скриншотом настроек. Подписывается
ТЕЛО ЦЕЛИКОМ вместе с меткой времени: без метки перехваченный запрос можно
переслать повторно, и подпись останется верной навсегда.

ДОСТАВКА ЧЕРЕЗ ОЧЕРЕДЬ ЗАДАЧ, а не прямо из обработчика события. Чужой
сервер отвечает когда захочет и падает когда захочет; ждать его внутри
публикации поста значит поставить скорость нашей системы в зависимость от
чужой. Плюс очередь переживает рестарт — событие не потеряется.

ДОСТАВКА «ХОТЯ БЫ ОДИН РАЗ», И ЭТО НАПИСАНО В ТЕЛЕ. Ретраи неизбежны:
ответ мог потеряться уже после того, как получатель всё сделал. Поэтому в
каждом событии есть `event_id`, и получатель обязан уметь его отбрасывать.
Обещать «ровно один раз» было бы враньём — этого не умеет никто.

ПОДПИСКА ОТКЛЮЧАЕТСЯ САМА после серии отказов. Вечно стучаться в мёртвый
адрес — это очередь, занятая тем, чего никто не ждёт, и растущий журнал
ошибок, в котором тонут настоящие.

⚠️ АДРЕС ЗАДАЁТ ВЛАДЕЛЕЦ, И ЭТО ОРУЖИЕ. Запрос уходит С НАШЕГО СЕРВЕРА,
изнутри сети. Адрес вида `http://169.254.169.254/...` заставил бы систему
сходить в метаданные облака и отдать наружу ключи самого сервера — классика
SSRF. Поэтому внутренние и служебные адреса отклоняются при сохранении.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from tg_repost import task_queue
from tg_repost.db.models import Webhook
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

TASK_KIND = "webhook_delivery"

# События. Список закрытый: «шлём всё подряд» означало бы, что новое
# внутреннее событие однажды уедет наружу без чьего-либо решения.
EVENT_POST_PUBLISHED = "post.published"
EVENT_MEMBER_JOINED = "member.joined"
EVENT_AD_REQUEST = "ad_request.created"
EVENT_PAYMENT = "payment.received"
KNOWN_EVENTS = (
    EVENT_POST_PUBLISHED,
    EVENT_MEMBER_JOINED,
    EVENT_AD_REQUEST,
    EVENT_PAYMENT,
)

# После скольких отказов подряд подписка выключается.
MAX_FAILURES = 10
# Сколько ждать чужой сервер. Больше — и очередь встанет на нём.
TIMEOUT_SECONDS = 10.0

SIGNATURE_HEADER = "X-Signature"
TIMESTAMP_HEADER = "X-Timestamp"
EVENT_HEADER = "X-Event"


class InvalidWebhook(ValueError):
    """Подписка не прошла проверку."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class WebhookView:
    id: int
    url: str
    events: tuple[str, ...]
    is_active: bool
    failure_streak: int
    last_error: str | None
    last_delivery_at: datetime | None


def _view(row: Webhook) -> WebhookView:
    return WebhookView(
        id=row.id,
        url=row.url,
        events=tuple(e for e in row.events.split(",") if e),
        is_active=row.is_active,
        failure_streak=row.failure_streak,
        last_error=row.last_error,
        last_delivery_at=row.last_delivery_at,
    )


def _reject_internal_address(url: str) -> None:
    """Не дать превратить вебхук в инструмент разведки нашей же сети.

    Проверяется РАЗРЕШЁННОЕ ИМЯ, а не строка: `http://internal.example.com`
    может указывать на 127.0.0.1, и проверка по тексту адреса это пропустит.
    Полностью SSRF так не закрыть (имя перерезолвится к моменту запроса), но
    отсекается всё, что делается по невнимательности и с первого раза.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise InvalidWebhook("Адрес должен начинаться с http:// или https://")
    host = parsed.hostname
    if not host:
        raise InvalidWebhook("В адресе нет хоста")

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # Имя не разрешается сейчас — это не повод запрещать: сервер
        # получателя может подняться позже. Опасны не «мёртвые» адреса, а
        # живые внутренние.
        return

    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
        ):
            raise InvalidWebhook(
                f"Адрес {address} — внутренний. Вебхук уходит с сервера системы, "
                "и такой адрес отдал бы наружу её собственное окружение."
            )


def save(
    url: str,
    *,
    webhook_id: int | None = None,
    events: list[str] | None = None,
    is_active: bool = True,
) -> int:
    clean_url = url.strip()
    if not clean_url:
        raise InvalidWebhook("Адрес не может быть пустым")
    _reject_internal_address(clean_url)

    chosen = [e for e in (events or []) if e]
    unknown = [e for e in chosen if e not in KNOWN_EVENTS]
    if unknown:
        raise InvalidWebhook(f"Неизвестные события: {', '.join(unknown)}")

    with session_scope() as session:
        row = session.get(Webhook, webhook_id) if webhook_id is not None else None
        if row is None:
            row = Webhook(url=clean_url, secret=secrets.token_urlsafe(32))
            session.add(row)
        row.url = clean_url
        row.events = ",".join(chosen)
        row.is_active = is_active
        # Правка адреса сбрасывает счётчик отказов: чинили, вероятно, именно
        # его, и заставлять владельца отдельно «включить обратно» — лишний
        # шаг, о котором он не догадается.
        row.failure_streak = 0
        row.last_error = None
        session.flush()
        return row.id


def get(webhook_id: int) -> WebhookView | None:
    with session_scope() as session:
        row = session.get(Webhook, webhook_id)
        return _view(row) if row is not None else None


def list_all() -> list[WebhookView]:
    with session_scope() as session:
        rows = session.query(Webhook).order_by(Webhook.id.asc()).all()
        return [_view(row) for row in rows]


def delete(webhook_id: int) -> bool:
    with session_scope() as session:
        row = session.get(Webhook, webhook_id)
        if row is None:
            return False
        session.delete(row)
        return True


def sign(secret: str, timestamp: str, body: str) -> str:
    """Подпись тела вместе с меткой времени.

    Метка входит в подпись обязательно: без неё перехваченный запрос можно
    переслать повторно, и подпись останется верной навсегда.
    """
    message = f"{timestamp}.{body}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def emit(event: str, payload: dict) -> int:
    """Поставить событие в очередь доставки. Возвращает число подписок.

    Ставит задачу, а не шлёт: чужой сервер отвечает когда захочет, и ждать
    его внутри публикации поста значит поставить нашу скорость в зависимость
    от чужой.
    """
    if event not in KNOWN_EVENTS:
        logger.warning("F73: попытка отправить неизвестное событие %s", event)
        return 0

    with session_scope() as session:
        rows = session.query(Webhook).filter(Webhook.is_active.is_(True)).all()
        targets = [
            row.id for row in rows
            if not row.events or event in row.events.split(",")
        ]

    for webhook_id in targets:
        task_queue.enqueue(
            TASK_KIND,
            {
                "webhook_id": webhook_id,
                "event": event,
                # Идентификатор события — для отбрасывания повторов на
                # стороне получателя: доставка «хотя бы один раз».
                "event_id": secrets.token_hex(8),
                "payload": payload,
            },
        )
    if targets:
        logger.info("F73: событие %s поставлено в доставку (%d)", event, len(targets))
    return len(targets)


def _record_success(webhook_id: int) -> None:
    with session_scope() as session:
        row = session.get(Webhook, webhook_id)
        if row is None:
            return
        row.failure_streak = 0
        row.last_error = None
        row.last_delivery_at = _utcnow()


def toggle_webhook(webhook_id: int) -> bool | None:
    """Переключить подписку. `None` — подписки нет.

    ЗАЧЕМ ЭТО НУЖНО ОТДЕЛЬНО. Вебхук выключает САМА СИСТЕМА — после серии
    отказов подряд (см. `_record_failure`). Приёмник полежал пять минут, и
    подписка мертва; включить её обратно из админки было нечем, оставалось
    удалить и завести заново, потеряв адрес и секрет. Это хуже, чем у
    источников: там владелец выключал сам и знал об этом.

    СЧЁТЧИК ОТКАЗОВ СБРАСЫВАЕТСЯ ПРИ ВКЛЮЧЕНИИ. Без этого подписка умирала бы
    снова на первом же следующем отказе: счётчик уже на пределе, и порог
    срабатывает мгновенно.
    """
    with session_scope() as session:
        row = session.get(Webhook, webhook_id)
        if row is None:
            return None
        row.is_active = not row.is_active
        if row.is_active:
            row.failure_streak = 0
            row.last_error = None
        return row.is_active


def _record_failure(webhook_id: int, error: str) -> None:
    with session_scope() as session:
        row = session.get(Webhook, webhook_id)
        if row is None:
            return
        row.failure_streak += 1
        row.last_error = error[:255]
        if row.failure_streak >= MAX_FAILURES:
            row.is_active = False
            logger.warning(
                "F73: вебхук #%d отключён после %d отказов подряд",
                webhook_id, row.failure_streak,
            )


async def handle_delivery(view) -> str | None:  # task_queue.TaskView
    """Обработчик очереди: доставить одно событие в одну подписку."""
    import httpx

    payload = view.payload
    webhook_id = int(payload["webhook_id"])

    with session_scope() as session:
        row = session.get(Webhook, webhook_id)
        if row is None or not row.is_active:
            # Подписку удалили или отключили, пока задача ждала. Это не сбой:
            # доставлять больше некуда.
            return None
        url, secret = row.url, row.secret

    body = json.dumps(
        {
            "event": payload["event"],
            "event_id": payload["event_id"],
            "data": payload["payload"],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    timestamp = str(int(_utcnow().timestamp()))

    # ОТКАЗ ЗАСЧИТЫВАЕТСЯ ОДИН РАЗ НА СОБЫТИЕ, А НЕ НА ПОПЫТКУ. Очередь
    # повторяет задачу трижды; считая каждую попытку, счётчик «отказов
    # подряд» рос бы втрое быстрее собственного названия, и подписка
    # умирала бы после трёх с небольшим событий вместо десяти. Владелец при
    # этом видел бы в админке «10 отказов» там, где событий было три.
    is_last_attempt = view.attempts >= task_queue.MAX_ATTEMPTS

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.post(
                url,
                content=body.encode(),
                headers={
                    "Content-Type": "application/json",
                    EVENT_HEADER: payload["event"],
                    TIMESTAMP_HEADER: timestamp,
                    SIGNATURE_HEADER: sign(secret, timestamp, body),
                },
            )
        if response.status_code >= 400:
            # Поднимаем, чтобы очередь повторила: 500 у получателя — это
            # обычно временно.
            raise RuntimeError(f"вебхук ответил {response.status_code}")
    except Exception as exc:
        if is_last_attempt:
            _record_failure(webhook_id, str(exc))
        raise

    _record_success(webhook_id)
    return None


def register_handler() -> None:
    task_queue.register(TASK_KIND, handle_delivery)
