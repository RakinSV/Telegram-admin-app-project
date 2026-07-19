"""Экспорт содержимого канала в независимый от системы формат (F38) —
JSON/CSV со всеми опубликованными постами, для передачи новому владельцу
канала или архива для комплаенса. `backup.py` уже бэкапит саму БД целиком —
это ДРУГОЕ: читаемый людьми/сторонними инструментами формат содержимого,
а не снимок SQLite-файла для восстановления системы."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime

from tg_repost.db.models import Post, PostStat, PostStatus, PostTarget
from tg_repost.db.session import session_scope

_CSV_FIELDS = [
    "id", "kind", "original_text", "rewritten_text", "source_link",
    "media_path", "created_at", "posted_at",
    "view_count", "forward_count", "reaction_count", "targets",
]


def _post_row(post: Post, targets: list[PostTarget], latest_stat: PostStat | None) -> dict:
    return {
        "id": post.id,
        "kind": post.kind.value,
        "original_text": post.original_text,
        "rewritten_text": post.rewritten_text,
        "source_link": post.source_link,
        "media_path": post.media_path,
        "created_at": post.created_at.isoformat() if post.created_at else None,
        "posted_at": post.posted_at.isoformat() if post.posted_at else None,
        "targets": [
            {"chat_id": t.chat_id, "message_id": t.message_id, "ok": t.ok} for t in targets
        ],
        "view_count": latest_stat.view_count if latest_stat else None,
        "forward_count": latest_stat.forward_count if latest_stat else None,
        "reaction_count": latest_stat.reaction_count if latest_stat else None,
    }


def export_posts(since: datetime | None = None, until: datetime | None = None) -> list[dict]:
    """Данные всех опубликованных (`POSTED`) постов за период — общий сбор
    для JSON/CSV сериализации ниже. `since`/`until` фильтруют по
    `posted_at`; оба `None` — весь опубликованный архив."""
    with session_scope() as session:
        query = session.query(Post).filter(Post.status == PostStatus.POSTED)
        if since is not None:
            query = query.filter(Post.posted_at >= since)
        if until is not None:
            query = query.filter(Post.posted_at <= until)
        posts = query.order_by(Post.posted_at).all()

        rows = []
        for post in posts:
            targets = (
                session.query(PostTarget).filter(PostTarget.post_id == post.id).all()
            )
            latest_stat = (
                session.query(PostStat)
                .filter(PostStat.post_id == post.id)
                .order_by(PostStat.captured_at.desc())
                .first()
            )
            rows.append(_post_row(post, targets, latest_stat))
        return rows


def export_posts_json(since: datetime | None = None, until: datetime | None = None) -> str:
    return json.dumps(export_posts(since, until), ensure_ascii=False, indent=2)


# Экранирование CSV/формул-инъекции (OWASP) — только для полей, реально
# приходящих из чужого спарсенного канала (`original_text`/`rewritten_text`/
# `source_link`, полностью управляемы посторонним). Ячейка, начинающаяся с
# одного из этих символов, интерпретируется Excel/Sheets как формула
# (`=HYPERLINK(...)`, `=cmd|...`) — ведущий апостроф заставляет открыть её
# как обычный текст (найдено на аудите). НЕ применяется ко всей строке
# целиком — системные поля вроде `targets` легитимно начинаются с "-"
# (отрицательный chat_id), эскейпить их — портить данные, не защищать.
_FORMULA_LEAD_CHARS = ("=", "+", "-", "@", "\t", "\r")
_CSV_ESCAPE_FIELDS = ("original_text", "rewritten_text", "source_link")


def _csv_safe(value: object) -> object:
    if isinstance(value, str) and value.startswith(_FORMULA_LEAD_CHARS):
        return "'" + value
    return value


def export_posts_csv(since: datetime | None = None, until: datetime | None = None) -> str:
    rows = export_posts(since, until)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_FIELDS)
    writer.writeheader()
    for row in rows:
        flat = dict(row)
        # CSV — плоский формат, список целей сворачиваем в одну строку
        # "chat_id:message_id; ..." (полная структура доступна в JSON-экспорте).
        flat["targets"] = "; ".join(
            f"{t['chat_id']}:{t['message_id']}" for t in row["targets"]
        )
        writer.writerow({
            key: _csv_safe(value) if key in _CSV_ESCAPE_FIELDS else value
            for key, value in flat.items()
        })
    return buf.getvalue()
