"""Рассылки по сегменту (F64).

Здесь сходятся три построенные раньше вещи: сегмент даёт людей, реестр
подписчиков говорит, кому можно писать, очередь делает отправку
возобновляемой. Поэтому и тесты в основном про стыки, а не про отправку
как таковую.

Главное, что защищаем: ПОСЛЕ ОБРЫВА НИКТО НЕ ПОЛУЧИТ СООБЩЕНИЕ ДВАЖДЫ.
Ошибка здесь видна только на живой аудитории и выглядит как спам от
владельца — извиниться можно, отозвать нельзя.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tg_repost import (
    broadcasts_repo,
    contacts_repo,
    segments_repo,
    subscribers_repo,
    task_queue,
)
from tg_repost.db.models import Broadcast, BotSubscriber, ContactSegment, ContactTag, QueuedTask
from tg_repost.db.session import session_scope


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(Broadcast).delete()
            session.query(QueuedTask).delete()
            session.query(BotSubscriber).delete()
            session.query(ContactTag).delete()
            session.query(ContactSegment).delete()
        task_queue._handlers.clear()

    _wipe()
    yield
    _wipe()


@pytest.fixture
def _bot(monkeypatch) -> AsyncMock:
    """Подменяем бота из супервизора: отправлять по-настоящему некуда."""
    bot = AsyncMock()
    bot.send_message = AsyncMock()

    class _Components:
        # Поле называется как в супервизоре: бот модерации теперь хранится
        # прямо, без объекта-приложения (aiogram).
        moderation_bot = bot

    monkeypatch.setattr(
        "tg_repost.webui.supervisor.get_components", lambda: _Components(),
    )
    # Паузы между отправками не нужны в тестах: они проверяются отдельно
    # самим фактом наличия, а не длительностью.
    async def _no_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr("tg_repost.broadcasts_repo.jitter_sleep", _no_sleep)
    broadcasts_repo.register_handler()
    return bot


def _segment_with(user_ids: list[int], *, reachable: bool = True) -> int:
    for user_id in user_ids:
        contacts_repo.add_tag(user_id, "рассылка")
        if reachable:
            subscribers_repo.record_contact(user_id)
    return segments_repo.save("Тест", {"tag": "рассылка"})


# --- предпросмотр ---


def test_plan_shows_both_numbers():
    """Разрыв между «в сегменте» и «достижимы» — главное, что видит владелец.

    «Отправлено 1 из 3» после отправки выглядит как сбой; та же цифра до
    отправки — как понятное ограничение Telegram.
    """
    contacts_repo.add_tag(1, "рассылка")
    contacts_repo.add_tag(2, "рассылка")
    contacts_repo.add_tag(3, "рассылка")
    subscribers_repo.record_contact(1)
    segment_id = segments_repo.save("Тест", {"tag": "рассылка"})

    preview = broadcasts_repo.plan(segment_id)

    assert preview is not None
    assert preview.stats.total == 3
    assert preview.stats.reachable == 1
    assert preview.stats.never_started == 2


def test_plan_of_missing_segment_is_none():
    assert broadcasts_repo.plan(999999) is None


# --- создание ---


def test_create_enqueues_task_and_snapshots_numbers():
    segment_id = _segment_with([1, 2])

    broadcast_id = broadcasts_repo.create(segment_id, "Привет!")

    row = broadcasts_repo.get(broadcast_id)
    assert row is not None
    assert row.segment_size == 2
    assert row.reachable_size == 2
    assert row.task_id is not None
    assert row.segment_name == "Тест"  # имя сохранено на момент отправки


def test_empty_text_is_rejected():
    segment_id = _segment_with([1])

    assert broadcasts_repo.create(segment_id, "   ") is None


def test_create_for_missing_segment_is_none():
    assert broadcasts_repo.create(999999, "текст") is None


# --- отправка ---


async def test_sends_to_reachable_only(_bot):
    contacts_repo.add_tag(1, "рассылка")
    contacts_repo.add_tag(2, "рассылка")
    subscribers_repo.record_contact(1)  # второй бота не запускал
    segment_id = segments_repo.save("Тест", {"tag": "рассылка"})
    broadcast_id = broadcasts_repo.create(segment_id, "Привет!")

    await task_queue.run_pending()

    assert _bot.send_message.await_count == 1
    assert _bot.send_message.await_args.args[0] == 1
    row = broadcasts_repo.get(broadcast_id)
    assert row is not None and row.sent_count == 1


async def test_every_message_carries_unsubscribe_button(_bot):
    """Без кнопки единственным способом прекратить поток остаётся блокировка
    бота — а это потеря человека целиком, вместе с ответами на его вопросы."""
    segment_id = _segment_with([1])
    broadcasts_repo.create(segment_id, "Привет!")

    await task_queue.run_pending()

    keyboard = _bot.send_message.await_args.kwargs["reply_markup"]
    button = keyboard.inline_keyboard[0][0]
    assert button.callback_data == "bcast:off"


async def test_resume_after_interruption_sends_no_duplicates(_bot):
    """ГЛАВНЫЙ ТЕСТ ФАЙЛА.

    Рассылка прерывается на середине, задача возвращается в очередь и
    продолжается. Каждый получатель обязан получить ровно одно сообщение:
    повтор виден только на живой аудитории и выглядит как спам.
    """
    segment_id = _segment_with([1, 2, 3, 4, 5])
    broadcasts_repo.create(segment_id, "Привет!")

    # Порция меньше числа получателей — задача не закончится за один заход.
    original_batch = broadcasts_repo.BATCH_SIZE
    broadcasts_repo.BATCH_SIZE = 2
    try:
        await task_queue.run_once()
        await task_queue.run_once()
        await task_queue.run_once()
        await task_queue.run_once()
    finally:
        broadcasts_repo.BATCH_SIZE = original_batch

    recipients = [call.args[0] for call in _bot.send_message.await_args_list]
    assert sorted(recipients) == [1, 2, 3, 4, 5]
    assert len(recipients) == len(set(recipients))  # ни одного повтора


async def test_blocked_user_is_counted_separately_and_not_retried(_bot):
    """Блокировка — не ошибка, а окончательное «нет» от человека."""
    segment_id = _segment_with([1])
    _bot.send_message.side_effect = Exception("Forbidden: bot was blocked by the user")
    broadcast_id = broadcasts_repo.create(segment_id, "Привет!")

    await task_queue.run_pending()

    row = broadcasts_repo.get(broadcast_id)
    assert row is not None
    assert row.blocked_count == 1
    assert row.failed_count == 0
    assert subscribers_repo.is_reachable(1) is False  # больше не пробуем


async def test_other_errors_counted_as_failures(_bot):
    segment_id = _segment_with([1])
    _bot.send_message.side_effect = Exception("Bad Gateway")
    broadcast_id = broadcasts_repo.create(segment_id, "Привет!")

    await task_queue.run_pending()

    row = broadcasts_repo.get(broadcast_id)
    assert row is not None
    assert row.failed_count == 1
    assert row.blocked_count == 0


async def test_one_failure_does_not_stop_the_rest(_bot):
    """Один недоступный получатель не должен обрывать рассылку остальным."""
    segment_id = _segment_with([1, 2, 3])
    calls = {"n": 0}

    async def _flaky(user_id, *_args, **_kwargs):
        calls["n"] += 1
        if user_id == 2:
            raise Exception("Bad Gateway")

    _bot.send_message.side_effect = _flaky
    broadcast_id = broadcasts_repo.create(segment_id, "Привет!")

    await task_queue.run_pending()

    row = broadcasts_repo.get(broadcast_id)
    assert row is not None
    assert row.sent_count == 2
    assert row.failed_count == 1


async def test_broadcast_finishes_and_is_marked_done(_bot):
    segment_id = _segment_with([1])
    broadcast_id = broadcasts_repo.create(segment_id, "Привет!")

    await task_queue.run_pending()

    row = broadcasts_repo.get(broadcast_id)
    assert row is not None
    assert row.status == broadcasts_repo.STATUS_DONE
    assert row.finished_at is not None


# --- отмена и крайние случаи ---


async def test_canceled_broadcast_sends_nothing_more(_bot):
    segment_id = _segment_with([1, 2, 3])
    broadcast_id = broadcasts_repo.create(segment_id, "Привет!")

    assert broadcasts_repo.cancel(broadcast_id) is True
    await task_queue.run_pending()

    assert _bot.send_message.await_count == 0


def test_cancel_finished_broadcast_is_false():
    segment_id = _segment_with([1])
    broadcast_id = broadcasts_repo.create(segment_id, "Привет!")
    broadcasts_repo.cancel(broadcast_id)

    assert broadcasts_repo.cancel(broadcast_id) is False


async def test_deleted_segment_stops_broadcast_without_crashing(_bot):
    """Сегмент удалили посреди рассылки — останавливаемся, а не падаем."""
    segment_id = _segment_with([1, 2])
    broadcast_id = broadcasts_repo.create(segment_id, "Привет!")
    segments_repo.delete(segment_id)

    await task_queue.run_pending()

    row = broadcasts_repo.get(broadcast_id)
    assert row is not None
    assert row.status == broadcasts_repo.STATUS_DONE


async def test_unsubscribed_person_receives_nothing(_bot):
    segment_id = _segment_with([1, 2])
    subscribers_repo.unsubscribe(2)
    broadcasts_repo.create(segment_id, "Привет!")

    await task_queue.run_pending()

    recipients = [call.args[0] for call in _bot.send_message.await_args_list]
    assert recipients == [1]
