"""Маркировка рекламы: пометка, erid и отчёт (F62).

ЕДИНСТВЕННОЕ МЕСТО ВО ВСЁМ БЭКЛОГЕ, ГДЕ ЦЕНА БЕЗДЕЙСТВИЯ — ШТРАФ, а не
упущенная выгода. Поэтому здесь всё устроено так, чтобы ошибка была
невозможна, а не маловероятна.

ПОМЕТКА ИДЁТ В НАЧАЛО ПОСТА, И ЭТО НЕ ВКУСОВЩИНА. Telegram сворачивает
длинный текст под «показать полностью»; пометка в конце оказалась бы за
этой границей, и формально она есть, а фактически её не видно. Смысл
маркировки — чтобы читатель СРАЗУ понимал, что перед ним реклама.

НАТИВНОСТЬ И МАРКИРОВКА НЕ ПРОТИВОРЕЧАТ ДРУГ ДРУГУ. В постановке F62 было
записано обратное, и это была ошибка рассуждения: обязанность привязана к
рекламе как таковой, а не к её формату. Нативный пост не перестаёт быть
рекламой оттого, что не выглядит ею. Выбор был не «нативно или с пометкой»,
а «продаём ли мы рекламу» — и он сделан владельцем.

ВЫКЛЮЧАТЕЛЬ ЕСТЬ, ЛАЗЕЙКИ НЕТ. Пока `ad_marking_enabled` выключен, система
ведёт себя как раньше. Как только он включён, рекламный пост БЕЗ erid не
публикуется вовсе — вместо «опубликовать без пометки» получается отказ с
объяснением. Публикация с частичной маркировкой хуже, чем непубликация:
пост уже ушёл к людям, отозвать его нельзя.

ИНТЕГРАЦИИ С API ОРД НЕТ. Регистрация креатива требует договора с
оператором и делается вне системы; владелец получает токен там и вставляет
его в бриф. Автоматизировать это, не имея договора, значило бы изображать
работу, которой не происходит.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from tg_repost.db.models import AdBrief, Post, PostKind, PostStatus, PostTarget
from tg_repost.db.session import session_scope

LABEL_WORD = "Реклама"


@dataclass(frozen=True)
class Marking:
    """Данные для пометки. Пустой `erid` означает «маркировать нечем»."""

    advertiser_legal_name: str | None
    advertiser_inn: str | None
    erid: str | None

    @property
    def is_complete(self) -> bool:
        """Готова ли пометка к публикации.

        ИНН необязателен намеренно: рекламодателем бывает физлицо или
        самозанятый, у которого ИНН в пометке не требуется, а вот имя и
        токен нужны всегда.
        """
        return bool((self.advertiser_legal_name or "").strip() and (self.erid or "").strip())


def marking_of(brief_id: int | None) -> Marking | None:
    """Маркировка брифа. `None` — брифа нет (или пост не рекламный)."""
    if brief_id is None:
        return None
    with session_scope() as session:
        row = session.get(AdBrief, brief_id)
        if row is None:
            return None
        return Marking(
            advertiser_legal_name=row.advertiser_legal_name,
            advertiser_inn=row.advertiser_inn,
            erid=row.erid,
        )


def build_label(marking: Marking) -> str:
    """Строка пометки: «Реклама. <кто>, ИНН <...>. erid: <токен>».

    Формат один на всю систему и не настраивается: настраиваемая пометка —
    это способ случайно её испортить, а цена опечатки тут не косметическая.
    """
    parts = [LABEL_WORD]
    who = (marking.advertiser_legal_name or "").strip()
    if who:
        inn = (marking.advertiser_inn or "").strip()
        parts.append(f"{who}, ИНН {inn}" if inn else who)
    erid = (marking.erid or "").strip()
    if erid:
        parts.append(f"erid: {erid}")
    return ". ".join(parts)


def apply_label(text: str, marking: Marking) -> str:
    """Приписать пометку В НАЧАЛО текста — см. docstring модуля.

    Повторный вызов пометку НЕ дублирует: текст мог уже пройти через
    предпросмотр модерации, и вторая строка «Реклама…» выглядела бы как
    сбой системы.
    """
    label = build_label(marking)
    body = text or ""
    if body.lstrip().startswith(label):
        return body
    return f"{label}\n\n{body}" if body.strip() else label


@dataclass(frozen=True)
class ReportRow:
    """Строка отчёта ОРД: что, кому, когда и под каким токеном ушло."""

    post_id: int
    posted_at: datetime | None
    advertiser_legal_name: str | None
    advertiser_inn: str | None
    erid: str | None
    text: str
    chat_ids: tuple[int, ...]


def report(since: datetime | None = None, until: datetime | None = None) -> list[ReportRow]:
    """Опубликованные рекламные посты за период.

    В отчёт попадают и посты БЕЗ erid: это не досадный мусор, а главное, что
    владелец должен увидеть — размещения, по которым он ещё не отчитался.
    Тихо отфильтровать их значило бы показать красивый отчёт и спрятать
    ровно то, из-за чего приходят штрафы.
    """
    with session_scope() as session:
        query = (
            session.query(Post)
            .filter(Post.kind == PostKind.AD, Post.status == PostStatus.POSTED)
        )
        if since is not None:
            query = query.filter(Post.posted_at >= since)
        if until is not None:
            query = query.filter(Post.posted_at <= until)
        posts = query.order_by(Post.posted_at.asc(), Post.id.asc()).all()

        rows: list[ReportRow] = []
        for post in posts:
            brief = session.get(AdBrief, post.ad_brief_id) if post.ad_brief_id else None
            targets = (
                session.query(PostTarget)
                .filter(PostTarget.post_id == post.id, PostTarget.ok.is_(True))
                .all()
            )
            rows.append(
                ReportRow(
                    post_id=post.id,
                    posted_at=post.posted_at,
                    advertiser_legal_name=brief.advertiser_legal_name if brief else None,
                    advertiser_inn=brief.advertiser_inn if brief else None,
                    erid=brief.erid if brief else None,
                    text=post.rewritten_text or post.original_text or "",
                    chat_ids=tuple(t.chat_id for t in targets),
                )
            )
        return rows


def unmarked_count(since: datetime | None = None) -> int:
    """Сколько опубликованных реклам осталось без erid.

    Отдельная функция, потому что это число нужно на видном месте, а не
    внутри отчёта, который ещё надо открыть.
    """
    return sum(1 for row in report(since) if not (row.erid or "").strip())
