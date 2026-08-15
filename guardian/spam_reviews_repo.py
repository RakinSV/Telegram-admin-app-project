"""Очередь спорных вердиктов и обучающая выборка антиспама (F57).

Подсмотрено у tg-spam (umputun): спорные случаи уходят модератору с
кнопками, и каждое решение делает классификатор точнее ИМЕННО НА ЭТОЙ
аудитории — там, где граница между спамом и своими шутками про заработок
у каждого чата своя.

Два места здесь неочевидны, и оба решают реальную проблему, а не гипотезу.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from guardian.db.models import SpamReview
from guardian.db.session import session_scope
from guardian.logging_conf import get_logger

logger = get_logger(__name__)

# Обрезка текста при записи: в промпт всё равно уйдёт короткий пример, а
# хранить у себя простыни чужой переписки незачем.
MAX_TEXT_LEN = 1000

LABEL_SPAM = "spam"
LABEL_HAM = "ham"

_WHITESPACE = re.compile(r"\s+")


def normalized_hash(text: str) -> str:
    """Хэш текста, нечувствительный к регистру и лишним пробелам.

    Спамеры рассылают одно и то же с косметическими отличиями; сравнивать
    сырые строки значило бы ловить только буквальные повторы.
    """
    normalized = _WHITESPACE.sub(" ", text.strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def enqueue(
    *,
    chat_id: int,
    user_id: int,
    text: str,
    kind: str,
    model_said_spam: bool | None = None,
    confidence: float | None = None,
) -> int | None:
    """Поставить спорный вердикт в очередь. `None` — такой уже ждёт разметки.

    ЗАЩИТА ОТ ПОТОКА. Спамер, отправивший пятьдесят одинаковых сообщений,
    иначе превратил бы лог-канал в ленту из пятидесяти одинаковых запросов —
    и владелец перестал бы читать её целиком, вместе с полезными. Поэтому
    неразмеченный вердикт с тем же текстом второй раз не заводится.

    Проверяется именно НЕРАЗМЕЧЕННЫЙ: если владелец уже вынес решение, а
    текст пришёл снова спустя время, это новый случай — возможно, решение
    изменилось.
    """
    digest = normalized_hash(text)
    with session_scope() as session:
        pending = (
            session.query(SpamReview.id)
            .filter(
                SpamReview.text_hash == digest,
                SpamReview.label.is_(None),
            )
            .first()
        )
        if pending:
            return None

        review = SpamReview(
            chat_id=chat_id,
            user_id=user_id,
            message_text=text[:MAX_TEXT_LEN],
            text_hash=digest,
            kind=kind,
            model_said_spam=model_said_spam,
            confidence=confidence,
        )
        session.add(review)
        session.flush()
        return review.id


def chat_of(review_id: int) -> int | None:
    """Чат, из которого пришёл спорный вердикт. `None` — записи нет.

    Нужен для проверки прав: кнопки нажимают в лог-канале, а право размечать
    определяется админством в ИСХОДНОМ чате — том, чью аудиторию эта разметка
    и настраивает.
    """
    with session_scope() as session:
        review = session.get(SpamReview, review_id)
        return review.chat_id if review else None


def set_label(review_id: int, label: str) -> bool:
    """Записать решение владельца. `False` — записи нет или метка неизвестна."""
    if label not in (LABEL_SPAM, LABEL_HAM):
        return False
    with session_scope() as session:
        review = session.get(SpamReview, review_id)
        if review is None:
            return False
        review.label = label
        review.labeled_at = datetime.now(timezone.utc)
        return True


def pending_count() -> int:
    with session_scope() as session:
        return session.query(SpamReview).filter(SpamReview.label.is_(None)).count()


@dataclass(frozen=True)
class Example:
    text: str
    is_spam: bool


def few_shot_examples(limit_per_label: int = 5) -> list[Example]:
    """Размеченные примеры для промпта — ПОРОВНУ спама и не-спама.

    БАЛАНС ОБЯЗАТЕЛЕН, и это второе неочевидное место. Размечать тянет
    прежде всего спам: он раздражает, его замечают. Если сложить примеры как
    есть, в промпт уедут двадцать спамов и один нормальный текст, и модель
    научится ровно одному — называть спамом всё подряд. Фильтр станет
    агрессивнее, а не точнее, то есть F57 сделает хуже, чем было.

    Поэтому берётся не более `limit_per_label` каждой метки, и берутся
    СВЕЖИЕ: спам меняется, прошлогодние схемы учат вчерашней войне.
    """
    out: list[Example] = []
    with session_scope() as session:
        for label in (LABEL_SPAM, LABEL_HAM):
            rows = (
                session.query(SpamReview.message_text)
                .filter(SpamReview.label == label)
                # Тай-брейк по `id` — при совпадении меток времени порядок
                # иначе не определён (та же причина, что в post_stats_repo).
                .order_by(SpamReview.labeled_at.desc(), SpamReview.id.desc())
                .limit(limit_per_label)
                .all()
            )
            out.extend(Example(text=row[0], is_spam=label == LABEL_SPAM) for row in rows)
    return out


def format_examples_block(examples: list[Example], max_chars: int = 2000) -> str:
    """Примеры → кусок промпта. Пустая строка, если примеров нет.

    `max_chars` — потолок на весь блок: обучающая выборка растёт бесконечно,
    а промпт оплачивается на КАЖДОМ вызове классификатора. Без потолка
    стоимость модерации тихо росла бы вместе с числом размеченных примеров.
    """
    if not examples:
        return ""

    lines: list[str] = []
    used = 0
    for example in examples:
        verdict = "СПАМ" if example.is_spam else "НЕ СПАМ"
        # Каждый пример в одну строку: перевод строки внутри примера сбил бы
        # разбор на стороне модели.
        text = _WHITESPACE.sub(" ", example.text.strip())[:300]
        line = f"- «{text}» → {verdict}"
        if used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line)

    if not lines:
        return ""
    return (
        "\n\nПримеры решений владельца этого чата (они важнее общих правил, "
        "потому что отражают его аудиторию):\n" + "\n".join(lines)
    )
