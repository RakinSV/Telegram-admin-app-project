"""Исходящие вебхуки (F73).

Вебхук уходит С НАШЕГО СЕРВЕРА по адресу, который задал человек. Поэтому
тесты не столько про «доставка работает», сколько про то, что этим нельзя
воспользоваться против самой системы и что чужой упавший сервер её не
останавливает.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tg_repost import task_queue, webhooks_repo as hooks
from tg_repost.db.models import QueuedTask, Webhook
from tg_repost.db.session import session_scope

URL = "https://example.com/hook"


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(Webhook).delete()
            session.query(QueuedTask).delete()
        task_queue._handlers.clear()

    _wipe()
    yield
    _wipe()


@pytest.fixture
def _external_dns(monkeypatch):
    """Разрешение имён в ВНЕШНИЙ адрес — иначе example.com в CI может не
    разрешиться, и тест проверял бы не то, что задуман."""
    monkeypatch.setattr(
        hooks.socket, "getaddrinfo",
        lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )


# --- защита от обращения внутрь сети ---


@pytest.mark.parametrize(
    "address",
    [
        "http://127.0.0.1/hook",
        "http://localhost/hook",
        "http://169.254.169.254/latest/meta-data/",
        "http://192.168.1.10/hook",
        "http://10.0.0.5/hook",
    ],
)
def test_internal_address_is_refused(address):
    """ГЛАВНАЯ ОПАСНОСТЬ ФИЧИ.

    Запрос уходит изнутри нашей сети. Адрес метаданных облака заставил бы
    систему сходить за ключами собственного сервера и отдать их наружу.
    """
    with pytest.raises(hooks.InvalidWebhook):
        hooks.save(address)


def test_hostname_pointing_inside_is_refused(monkeypatch):
    """Проверяется РАЗРЕШЁННОЕ ИМЯ, а не текст адреса: `internal.example.com`
    может указывать на 127.0.0.1, и проверка по строке это пропустит."""
    monkeypatch.setattr(
        hooks.socket, "getaddrinfo",
        lambda *a, **kw: [(2, 1, 6, "", ("127.0.0.1", 0))],
    )

    with pytest.raises(hooks.InvalidWebhook):
        hooks.save("https://internal.example.com/hook")


def test_unresolvable_name_is_allowed(monkeypatch):
    """Сервер получателя может подняться позже. Опасны живые внутренние
    адреса, а не мёртвые."""
    def _boom(*a, **kw):
        raise hooks.socket.gaierror("нет такого имени")

    monkeypatch.setattr(hooks.socket, "getaddrinfo", _boom)

    assert hooks.save("https://not-yet.example.com/hook") > 0


@pytest.mark.parametrize("address", ["ftp://example.com", "file:///etc/passwd", "мусор"])
def test_non_http_scheme_is_refused(address):
    with pytest.raises(hooks.InvalidWebhook):
        hooks.save(address)


def test_unknown_event_is_refused(_external_dns):
    """Список событий закрытый: «шлём всё подряд» означало бы, что новое
    внутреннее событие однажды уедет наружу без чьего-либо решения."""
    with pytest.raises(hooks.InvalidWebhook):
        hooks.save(URL, events=["всё"])


# --- подпись ---


def test_signature_covers_the_body(_external_dns):
    """Без подписи получатель не отличит наш вызов от чужого, знающего адрес."""
    first = hooks.sign("секрет", "100", '{"a":1}')
    other = hooks.sign("секрет", "100", '{"a":2}')

    assert first != other


def test_signature_covers_the_timestamp():
    """Без метки времени перехваченный запрос можно переслать повторно, и
    подпись останется верной навсегда."""
    assert hooks.sign("секрет", "100", "{}") != hooks.sign("секрет", "200", "{}")


def test_signature_depends_on_the_secret():
    assert hooks.sign("один", "100", "{}") != hooks.sign("другой", "100", "{}")


def test_each_webhook_gets_its_own_secret(_external_dns):
    """Общий секрет означал бы, что один получатель может подделать вызов
    к другому."""
    first = hooks.save(URL, events=[])
    second = hooks.save("https://example.com/second", events=[])

    with session_scope() as session:
        secrets_used = {
            session.get(Webhook, first).secret,
            session.get(Webhook, second).secret,
        }

    assert len(secrets_used) == 2


# --- постановка в очередь ---


def test_event_is_queued_not_sent_inline(_external_dns):
    """Чужой сервер отвечает когда захочет; ждать его внутри публикации
    поста значит поставить нашу скорость в зависимость от чужой."""
    hooks.save(URL, events=[hooks.EVENT_POST_PUBLISHED])

    count = hooks.emit(hooks.EVENT_POST_PUBLISHED, {"post_id": 1})

    assert count == 1
    with session_scope() as session:
        assert session.query(QueuedTask).count() == 1


def test_webhook_only_gets_events_it_asked_for(_external_dns):
    hooks.save(URL, events=[hooks.EVENT_PAYMENT])

    assert hooks.emit(hooks.EVENT_POST_PUBLISHED, {}) == 0
    assert hooks.emit(hooks.EVENT_PAYMENT, {}) == 1


def test_empty_event_list_means_everything(_external_dns):
    hooks.save(URL, events=[])

    assert hooks.emit(hooks.EVENT_POST_PUBLISHED, {}) == 1


def test_disabled_webhook_gets_nothing(_external_dns):
    hooks.save(URL, events=[], is_active=False)

    assert hooks.emit(hooks.EVENT_POST_PUBLISHED, {}) == 0


def test_unknown_event_is_never_emitted(_external_dns):
    hooks.save(URL, events=[])

    assert hooks.emit("внутреннее.событие", {}) == 0


def test_each_event_carries_its_own_id(_external_dns):
    """Доставка «хотя бы один раз»: получатель обязан уметь отбрасывать
    повторы, а для этого нужен идентификатор."""
    hooks.save(URL, events=[])
    hooks.emit(hooks.EVENT_POST_PUBLISHED, {})
    hooks.emit(hooks.EVENT_POST_PUBLISHED, {})

    with session_scope() as session:
        import json

        ids = {
            json.loads(row.payload)["event_id"]
            for row in session.query(QueuedTask).all()
        }

    assert len(ids) == 2


# --- доставка ---


async def test_successful_delivery_signs_the_request(_external_dns):
    webhook_id = hooks.save(URL, events=[])
    hooks.register_handler()
    hooks.emit(hooks.EVENT_POST_PUBLISHED, {"post_id": 7})

    sent = AsyncMock()
    sent.return_value.status_code = 200
    with patch("httpx.AsyncClient.post", sent):
        await task_queue.run_pending()

    headers = sent.await_args.kwargs["headers"]
    assert headers[hooks.SIGNATURE_HEADER]
    assert headers[hooks.TIMESTAMP_HEADER]
    view = hooks.get(webhook_id)
    assert view is not None and view.failure_streak == 0


async def test_failure_is_recorded(_external_dns):
    webhook_id = hooks.save(URL, events=[])
    hooks.register_handler()
    hooks.emit(hooks.EVENT_POST_PUBLISHED, {})

    failing = AsyncMock(side_effect=RuntimeError("сервер недоступен"))
    with patch("httpx.AsyncClient.post", failing):
        await task_queue.run_pending()

    view = hooks.get(webhook_id)
    assert view is not None
    assert view.failure_streak == 1
    assert view.last_error is not None


async def test_http_error_counts_as_failure(_external_dns):
    webhook_id = hooks.save(URL, events=[])
    hooks.register_handler()
    hooks.emit(hooks.EVENT_POST_PUBLISHED, {})

    sent = AsyncMock()
    sent.return_value.status_code = 500
    with patch("httpx.AsyncClient.post", sent):
        await task_queue.run_pending()

    assert hooks.get(webhook_id).failure_streak == 1


async def test_dead_endpoint_switches_itself_off(_external_dns):
    """Вечно стучаться в мёртвый адрес — это очередь, занятая тем, чего никто
    не ждёт, и журнал, в котором тонут настоящие ошибки."""
    webhook_id = hooks.save(URL, events=[])
    with session_scope() as session:
        session.get(Webhook, webhook_id).failure_streak = hooks.MAX_FAILURES - 1

    hooks._record_failure(webhook_id, "снова мимо")

    view = hooks.get(webhook_id)
    assert view is not None and view.is_active is False


def test_fixing_the_address_revives_the_webhook(_external_dns):
    """Чинили, вероятно, именно адрес; заставлять отдельно «включить
    обратно» — лишний шаг, о котором владелец не догадается."""
    webhook_id = hooks.save(URL, events=[])
    for _ in range(hooks.MAX_FAILURES):
        hooks._record_failure(webhook_id, "мимо")

    hooks.save("https://example.com/fixed", webhook_id=webhook_id, events=[])

    view = hooks.get(webhook_id)
    assert view is not None
    assert view.is_active is True
    assert view.failure_streak == 0


async def test_deleted_webhook_does_not_break_the_queue(_external_dns):
    """Подписку удалили, пока задача ждала. Это не сбой — доставлять некуда."""
    webhook_id = hooks.save(URL, events=[])
    hooks.register_handler()
    hooks.emit(hooks.EVENT_POST_PUBLISHED, {})
    hooks.delete(webhook_id)

    with patch("httpx.AsyncClient.post", AsyncMock()) as sent:
        await task_queue.run_pending()

    assert sent.await_count == 0
