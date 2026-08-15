"""Сегменты участников — сохранённые запросы (F63, основа F64).

СЕГМЕНТ — ЭТО ЗАПРОС, А НЕ СПИСОК. Материализованный список людей устаревает
молча: человек ушёл из чата, перестал подходить под условие, а рассылка всё
равно уходит ему — и узнаётся это по жалобам. Запрос вычисляется в момент
использования и всегда актуален. Плата — вычисление на каждое обращение, что
на масштабе одного владельца несущественно.

ГЛАВНАЯ ОПАСНОСТЬ ЭТОГО МОДУЛЯ — сегмент, который по ошибке совпадает со
ВСЕЙ базой. Опечатка в имени условия, пустой фильтр, «забыли сохранить
поле» — и рассылка уходит всем подряд, включая тех, кому её слать нельзя.
Отменить это невозможно: сообщения уже доставлены. Поэтому:

* неизвестные условия ОТВЕРГАЮТСЯ при сохранении, а не игнорируются;
* пустой фильтр ОТВЕРГАЕТСЯ;
* «все» — это отдельное явное условие `everyone`, которое надо написать
  руками. Случайно оно не появится.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from tg_repost.db.models import ContactSegment, ContactTag, MemberOrigin, UserActivity
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)


class InvalidFilter(ValueError):
    """Фильтр сегмента не прошёл проверку — сохранять его нельзя."""


# Условия, которые система умеет вычислять. Всё остальное — ошибка.
KNOWN_KEYS = frozenset({
    "everyone",     # bool: все известные участники. Только явно.
    "tag",          # str: есть такой тег
    "min_points",   # int: очков не меньше
    "origin",       # str: пришёл по этой кампании (invite_name)
    "active_only",  # bool: ещё не покинул чат
    "chat_id",      # int: только этот чат
})


def validate(filter_dict: dict) -> dict:
    """Проверить фильтр перед сохранением. Бросает `InvalidFilter`.

    Проверка строгая намеренно: молча проигнорированное условие превращает
    узкий сегмент в «вся база», а рассылку — в катастрофу, которую нельзя
    отменить.
    """
    if not isinstance(filter_dict, dict) or not filter_dict:
        raise InvalidFilter(
            "Пустой фильтр запрещён: он совпал бы со всей базой. "
            "Если нужны действительно все — укажите условие everyone."
        )

    unknown = set(filter_dict) - KNOWN_KEYS
    if unknown:
        raise InvalidFilter(
            f"Неизвестные условия: {', '.join(sorted(unknown))}. "
            f"Допустимые: {', '.join(sorted(KNOWN_KEYS))}"
        )

    if filter_dict.get("everyone") and len(filter_dict) > 1:
        raise InvalidFilter(
            "Условие everyone не сочетается с другими: непонятно, "
            "все или всё-таки по условию."
        )

    for key in ("min_points", "chat_id"):
        if key in filter_dict and not isinstance(filter_dict[key], int):
            raise InvalidFilter(f"Условие {key} должно быть числом")

    for key in ("tag", "origin"):
        if key in filter_dict and not str(filter_dict[key]).strip():
            raise InvalidFilter(f"Условие {key} не может быть пустым")

    return filter_dict


def evaluate(filter_dict: dict) -> list[int]:
    """Вычислить сегмент — id людей, подходящих под условия.

    Фильтр проверяется и здесь, а не только при сохранении: вызвать
    `evaluate` можно и с фильтром, собранным на лету, и незамеченная
    опечатка в этом случае стоила бы ровно столько же.
    """
    validate(filter_dict)

    with session_scope() as session:
        if filter_dict.get("everyone"):
            # «Все» — это все, кого система вообще видела: участники чатов и
            # те, у кого есть активность. Объединение, а не одна таблица:
            # человек мог отвечать на викторины, но не иметь записи о входе.
            origins = {
                row[0] for row in session.query(MemberOrigin.user_id).all()
            }
            actives = {row[0] for row in session.query(UserActivity.user_id).all()}
            return sorted(origins | actives)

        candidates: set[int] | None = None

        def _intersect(ids: set[int]) -> None:
            nonlocal candidates
            candidates = ids if candidates is None else (candidates & ids)

        if "tag" in filter_dict:
            tag = " ".join(str(filter_dict["tag"]).strip().lower().split())
            _intersect({
                row[0]
                for row in session.query(ContactTag.user_id)
                .filter(ContactTag.tag == tag)
                .all()
            })

        if "min_points" in filter_dict:
            query = session.query(UserActivity.user_id).filter(
                UserActivity.points >= filter_dict["min_points"]
            )
            if "chat_id" in filter_dict:
                query = query.filter(UserActivity.chat_id == filter_dict["chat_id"])
            _intersect({row[0] for row in query.all()})

        if "origin" in filter_dict or "active_only" in filter_dict or (
            "chat_id" in filter_dict and "min_points" not in filter_dict
        ):
            query = session.query(MemberOrigin.user_id)
            if "origin" in filter_dict:
                query = query.filter(MemberOrigin.invite_name == filter_dict["origin"])
            if filter_dict.get("active_only"):
                query = query.filter(MemberOrigin.left_at.is_(None))
            if "chat_id" in filter_dict:
                query = query.filter(MemberOrigin.chat_id == filter_dict["chat_id"])
            _intersect({row[0] for row in query.all()})

    # `candidates is None` здесь недостижимо: пустой фильтр отвергнут
    # проверкой выше, а каждое допустимое условие сужает множество.
    return sorted(candidates or set())


# --- сохранённые сегменты ---


@dataclass(frozen=True)
class SegmentView:
    id: int
    name: str
    filter: dict
    updated_at: datetime


def save(name: str, filter_dict: dict) -> int:
    """Создать или обновить сегмент по имени. Возвращает id."""
    validate(filter_dict)
    clean_name = name.strip()
    if not clean_name:
        raise InvalidFilter("Имя сегмента не может быть пустым")

    payload = json.dumps(filter_dict, ensure_ascii=False, sort_keys=True)
    with session_scope() as session:
        row = (
            session.query(ContactSegment)
            .filter(ContactSegment.name == clean_name)
            .first()
        )
        if row is None:
            row = ContactSegment(name=clean_name, filter_json=payload)
            session.add(row)
            session.flush()
        else:
            row.filter_json = payload
            row.updated_at = datetime.now(timezone.utc)
        return row.id


def get(segment_id: int) -> SegmentView | None:
    with session_scope() as session:
        row = session.get(ContactSegment, segment_id)
        if row is None:
            return None
        return SegmentView(
            id=row.id,
            name=row.name,
            filter=json.loads(row.filter_json),
            updated_at=row.updated_at,
        )


def list_all() -> list[SegmentView]:
    with session_scope() as session:
        rows = session.query(ContactSegment).order_by(ContactSegment.name.asc()).all()
        return [
            SegmentView(
                id=row.id,
                name=row.name,
                filter=json.loads(row.filter_json),
                updated_at=row.updated_at,
            )
            for row in rows
        ]


def delete(segment_id: int) -> bool:
    with session_scope() as session:
        row = session.get(ContactSegment, segment_id)
        if row is None:
            return False
        session.delete(row)
        return True


def members_of(segment_id: int) -> list[int]:
    """Кто сейчас в сегменте. Вычисляется, а не берётся из списка."""
    view = get(segment_id)
    if view is None:
        return []
    return evaluate(view.filter)
