"""Поддержка: единый инбокс обращений (F68).

Вопрос, написанный боту в личку, до сих пор не превращался ни во что. Для
бизнеса это обязательный блок: человек, которому не ответили, не пишет
второй раз — он уходит.

ОДИН ТРЕД НА ЧЕЛОВЕКА. Человек не мыслит «тикетами»: пишет, дописывает,
возвращается через неделю. Нарезка на обращения по таймауту породила бы три
треда об одном и том же и заставила оператора собирать историю по кускам.
Закрытый тред открывается заново новым сообщением — это и есть «вернулся с
тем же вопросом».

СВЯЗЬ С КАРТОЧКОЙ (F63) — не украшение. Оператор, отвечающий человеку, должен
видеть, откуда тот пришёл, сколько привёл друзей и не забанен ли он в
группе. Иначе поддержка отвечает незнакомцу.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from tg_repost.db.models import SupportMessage, SupportThread
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

STATUS_OPEN = "open"
STATUS_CLOSED = "closed"

DIRECTION_IN = "in"
DIRECTION_OUT = "out"

# Обрезка входящего текста. Поддержка — не файловое хранилище, а простыня в
# списке тредов делает его нечитаемым.
MAX_TEXT = 4000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ThreadView:
    id: int
    user_id: int
    username: str | None
    status: str
    has_unread: bool
    last_message_at: datetime
    message_count: int = 0


@dataclass(frozen=True)
class MessageView:
    id: int
    direction: str
    text: str
    author: str | None
    created_at: datetime


def record_incoming(
    user_id: int, text: str, *, username: str | None = None
) -> int | None:
    """Сохранить сообщение от человека. Возвращает id треда.

    `None` — пустой текст: сохранять нечего, а пустой тред в инбоксе выглядел
    бы как обращение, на которое забыли ответить.
    """
    body = text.strip()[:MAX_TEXT]
    if not body:
        return None

    with session_scope() as session:
        thread = (
            session.query(SupportThread)
            .filter(SupportThread.user_id == user_id)
            .first()
        )
        if thread is None:
            thread = SupportThread(user_id=user_id, username=username)
            session.add(thread)
            session.flush()
        else:
            # Новое сообщение открывает закрытый тред: человек вернулся, и
            # оставить его в «закрыто» значит потерять обращение.
            thread.status = STATUS_OPEN
            if username is not None:
                thread.username = username

        thread.has_unread = True
        thread.last_message_at = _utcnow()
        session.add(
            SupportMessage(
                thread_id=thread.id, direction=DIRECTION_IN, text=body,
            )
        )
        logger.info("F68: сообщение в поддержку от %s (тред #%d)", user_id, thread.id)
        return thread.id


def record_reply(thread_id: int, text: str, *, author: str) -> bool:
    """Сохранить ответ оператора. Отправку делает вызывающий."""
    body = text.strip()[:MAX_TEXT]
    if not body:
        return False

    with session_scope() as session:
        thread = session.get(SupportThread, thread_id)
        if thread is None:
            return False
        session.add(
            SupportMessage(
                thread_id=thread_id, direction=DIRECTION_OUT, text=body, author=author,
            )
        )
        # Ответили — значит прочитали. Отдельно снимать флаг не нужно, и
        # забыть это сделать тоже нельзя.
        thread.has_unread = False
        thread.last_message_at = _utcnow()
        return True


def set_status(thread_id: int, status: str) -> bool:
    if status not in (STATUS_OPEN, STATUS_CLOSED):
        return False
    with session_scope() as session:
        thread = session.get(SupportThread, thread_id)
        if thread is None:
            return False
        thread.status = status
        if status == STATUS_CLOSED:
            thread.has_unread = False
        return True


def mark_read(thread_id: int) -> bool:
    """Отметить прочитанным без ответа — оператор посмотрел и отложил."""
    with session_scope() as session:
        thread = session.get(SupportThread, thread_id)
        if thread is None:
            return False
        thread.has_unread = False
        return True


def get_thread(thread_id: int) -> ThreadView | None:
    with session_scope() as session:
        thread = session.get(SupportThread, thread_id)
        if thread is None:
            return None
        count = (
            session.query(SupportMessage)
            .filter(SupportMessage.thread_id == thread_id)
            .count()
        )
        return ThreadView(
            id=thread.id, user_id=thread.user_id, username=thread.username,
            status=thread.status, has_unread=thread.has_unread,
            last_message_at=thread.last_message_at, message_count=count,
        )


def list_threads(status: str | None = None, limit: int = 100) -> list[ThreadView]:
    """Инбокс. Непрочитанные сверху, дальше — по свежести.

    Порядок именно такой: оператор открывает страницу, чтобы увидеть, кому
    ещё не ответили, а не чтобы листать историю.
    """
    with session_scope() as session:
        query = session.query(SupportThread)
        if status is not None:
            query = query.filter(SupportThread.status == status)
        rows = (
            query.order_by(
                SupportThread.has_unread.desc(),
                SupportThread.last_message_at.desc(),
                SupportThread.id.desc(),
            )
            .limit(limit)
            .all()
        )
        counts = {
            row.id: session.query(SupportMessage)
            .filter(SupportMessage.thread_id == row.id)
            .count()
            for row in rows
        }
        return [
            ThreadView(
                id=row.id, user_id=row.user_id, username=row.username,
                status=row.status, has_unread=row.has_unread,
                last_message_at=row.last_message_at,
                message_count=counts.get(row.id, 0),
            )
            for row in rows
        ]


def messages_of(thread_id: int) -> list[MessageView]:
    with session_scope() as session:
        rows = (
            session.query(SupportMessage)
            .filter(SupportMessage.thread_id == thread_id)
            .order_by(SupportMessage.created_at.asc(), SupportMessage.id.asc())
            .all()
        )
        return [
            MessageView(
                id=row.id, direction=row.direction, text=row.text,
                author=row.author, created_at=row.created_at,
            )
            for row in rows
        ]


def unread_count() -> int:
    with session_scope() as session:
        return (
            session.query(SupportThread)
            .filter(SupportThread.has_unread.is_(True))
            .count()
        )
