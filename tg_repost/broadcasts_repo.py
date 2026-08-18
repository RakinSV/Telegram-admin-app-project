"""Рассылки по сегменту (F64).

Здесь сходятся три построенные раньше вещи: сегмент даёт список людей
(F63), реестр подписчиков отвечает, кому из них МОЖНО написать, а очередь
задач делает отправку возобновляемой после обрыва (фаза 11).

ЧЕТЫРЕ ПРАВИЛА, БЕЗ КОТОРЫХ РАССЫЛКА ОПАСНА:

1. **Кнопка отписки в КАЖДОМ сообщении.** Без неё единственный способ
   прекратить поток — заблокировать бота, а это потеря человека навсегда,
   включая ответы на его собственные вопросы.
2. **Блокировка бота — не ошибка.** Считается отдельно и не повторяется:
   человек уже сказал «нет» способом, который Telegram делает окончательным.
3. **Курсор по возрастанию `user_id`.** После обрыва рассылка продолжается,
   а не начинается заново — иначе половина базы получит сообщение дважды.
4. **Пауза между отправками.** Telegram ограничивает частоту, и рассылка,
   упёршаяся в лимит, получает бан на отправку целиком.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from tg_repost import segments_repo, subscribers_repo, task_queue
from tg_repost.antiban import jitter_sleep
from tg_repost.db.models import Broadcast
from tg_repost.db.session import session_scope
from aiogram.types import InlineKeyboardMarkup

from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

TASK_KIND = "broadcast"

# Сколько получателей обрабатываем за один заход обработчика. Не «сколько
# всего»: после порции задача возвращается в очередь, чтобы длинная рассылка
# не занимала воркер часами и не мешала другим задачам.
BATCH_SIZE = 25
# Пауза между сообщениями. Telegram допускает около 30 в секунду, но для
# массовых отправок разумно держаться заметно ниже: превышение стоит не
# задержки, а временного запрета на отправку.
_MIN_DELAY = 0.05
_MAX_DELAY = 0.15

STATUS_PLANNED = "planned"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_CANCELED = "canceled"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class BroadcastPlan:
    """Что произойдёт, если нажать «отправить». Показывается ДО отправки."""

    segment_name: str
    stats: subscribers_repo.ReachStats


def plan(segment_id: int) -> BroadcastPlan | None:
    """Предпросмотр: сколько людей в сегменте и скольким реально уйдёт.

    Разрыв между этими числами — главное, что владелец должен увидеть
    заранее. «Отправлено 120 из 8000» после отправки выглядит как сбой;
    та же цифра до отправки — как понятное ограничение Telegram.
    """
    view = segments_repo.get(segment_id)
    if view is None:
        return None
    members = segments_repo.evaluate(view.filter)
    return BroadcastPlan(
        segment_name=view.name, stats=subscribers_repo.reach_stats(members),
    )


def create(segment_id: int, text: str) -> int | None:
    """Создать рассылку и поставить её в очередь. Возвращает id рассылки."""
    body = text.strip()
    if not body:
        return None
    view = segments_repo.get(segment_id)
    if view is None:
        return None

    members = segments_repo.evaluate(view.filter)
    stats = subscribers_repo.reach_stats(members)

    with session_scope() as session:
        row = Broadcast(
            segment_id=segment_id,
            segment_name=view.name,
            text=body,
            status=STATUS_PLANNED,
            segment_size=stats.total,
            reachable_size=stats.reachable,
        )
        session.add(row)
        session.flush()
        broadcast_id = row.id

    task_id = task_queue.enqueue(
        TASK_KIND, {"broadcast_id": broadcast_id}, total_count=stats.reachable,
    )
    with session_scope() as session:
        created = session.get(Broadcast, broadcast_id)
        if created is not None:
            created.task_id = task_id
    logger.info(
        "F64: рассылка #%d по сегменту «%s»: %d в сегменте, %d достижимы",
        broadcast_id, view.name, stats.total, stats.reachable,
    )
    return broadcast_id


def get(broadcast_id: int) -> Broadcast | None:
    with session_scope() as session:
        row = session.get(Broadcast, broadcast_id)
        if row is not None:
            session.expunge(row)
        return row


def list_recent(limit: int = 50) -> list[Broadcast]:
    with session_scope() as session:
        rows = (
            session.query(Broadcast)
            .order_by(Broadcast.created_at.desc(), Broadcast.id.desc())
            .limit(limit)
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def cancel(broadcast_id: int) -> bool:
    """Остановить рассылку. Уже отправленное вернуть нельзя."""
    with session_scope() as session:
        row = session.get(Broadcast, broadcast_id)
        if row is None or row.status in (STATUS_DONE, STATUS_CANCELED):
            return False
        row.status = STATUS_CANCELED
        row.finished_at = _utcnow()
        task_id = row.task_id
    if task_id:
        task_queue.cancel(task_id)
    return True


def _bump(broadcast_id: int, *, sent: int = 0, blocked: int = 0, failed: int = 0) -> None:
    with session_scope() as session:
        row = session.get(Broadcast, broadcast_id)
        if row is None:
            return
        row.sent_count += sent
        row.blocked_count += blocked
        row.failed_count += failed
        if row.status == STATUS_PLANNED:
            row.status = STATUS_RUNNING


def _finish(broadcast_id: int) -> None:
    with session_scope() as session:
        row = session.get(Broadcast, broadcast_id)
        if row is None or row.status == STATUS_CANCELED:
            return
        row.status = STATUS_DONE
        row.finished_at = _utcnow()


def build_message(text: str) -> tuple[str, "InlineKeyboardMarkup"]:
    """Текст рассылки + клавиатура с кнопкой отписки.

    Кнопка обязательна в КАЖДОМ сообщении. Без неё единственным способом
    прекратить поток остаётся блокировка бота — а это потеря человека
    навсегда, включая ответы на его собственные вопросы.
    """
    from aiogram.types import InlineKeyboardButton

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔕 Отписаться от рассылок", callback_data="bcast:off"),
    ]])
    return text, keyboard


async def handle_broadcast_task(view: task_queue.TaskView) -> str | None:
    """Обработчик очереди: отправить очередную порцию получателей.

    Возвращает курсор (последний обработанный `user_id`) или `None`, когда
    рассылка закончена.
    """
    broadcast_id = int(view.payload["broadcast_id"])
    row = get(broadcast_id)
    if row is None:
        logger.warning("F64: рассылка #%s исчезла — задача завершается", broadcast_id)
        return None
    if row.status == STATUS_CANCELED:
        logger.info("F64: рассылка #%d отменена — задача завершается", broadcast_id)
        return None

    if row.segment_id is None:
        _finish(broadcast_id)
        return None
    segment = segments_repo.get(row.segment_id)
    if segment is None:
        # Сегмент удалили посреди рассылки. Продолжать не по чему, а молча
        # завершать нельзя — владелец должен понять, почему отправка встала.
        logger.warning(
            "F64: сегмент рассылки #%d удалён — отправлено %d, останавливаемся",
            broadcast_id, row.sent_count,
        )
        _finish(broadcast_id)
        return None

    members = segments_repo.evaluate(segment.filter)
    after = int(view.cursor) if view.cursor else None
    recipients = subscribers_repo.reachable_among(members, after_user_id=after)[:BATCH_SIZE]
    if not recipients:
        _finish(broadcast_id)
        logger.info(
            "F64: рассылка #%d завершена: доставлено %d, заблокировали %d, ошибок %d",
            broadcast_id, row.sent_count, row.blocked_count, row.failed_count,
        )
        return None

    from tg_repost.webui.supervisor import get_components

    bot = get_components().moderation_bot
    if bot is None:
        # Бот модерации не поднялся (нет токена, не отвечает Telegram) —
        # рассылать нечем. Отметок «отправлено» не ставим: следующий проход
        # воркера возьмёт ту же порцию, когда бот появится.
        logger.warning(
            "Рассылка %s отложена: бот модерации не запущен", broadcast_id,
        )
        return None
    text, keyboard = build_message(row.text)

    last_user_id = after
    for user_id in recipients:
        try:
            await bot.send_message(user_id, text, reply_markup=keyboard)
            _bump(broadcast_id, sent=1)
        except Exception as exc:  # noqa: BLE001 — разбираем по тексту ниже
            message = str(exc)
            if "blocked" in message.lower() or "bot was blocked" in message.lower():
                # Не ошибка: человек сказал «нет» способом, который Telegram
                # делает окончательным. Повторять бессмысленно.
                subscribers_repo.mark_blocked(user_id)
                _bump(broadcast_id, blocked=1)
            else:
                _bump(broadcast_id, failed=1)
                logger.warning("F64: не удалось отправить %s: %s", user_id, message[:200])

        last_user_id = user_id
        # Курсор двигается ПОСЛЕ каждого получателя, а не в конце порции:
        # обрыв посреди порции иначе повторил бы её целиком.
        view.progress(cursor=str(user_id))
        await jitter_sleep(_MIN_DELAY, _MAX_DELAY)

    return str(last_user_id)


def register_handler() -> None:
    """Подключить обработчик к очереди. Зовётся при старте приложения."""
    task_queue.register(TASK_KIND, handle_broadcast_task)
