"""Тесты F38 — экспорт содержимого канала (`export.py`)."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from tg_repost import post_targets_repo
from tg_repost.db.models import Post, PostKind, PostStat, PostStatus, PostTarget
from tg_repost.db.session import session_scope
from tg_repost.export import export_posts, export_posts_csv, export_posts_json


def _clean() -> None:
    with session_scope() as session:
        session.query(PostStat).delete()
        session.query(PostTarget).delete()
        session.query(Post).delete()


def _make_posted_post(**kwargs) -> Post:
    with session_scope() as session:
        post = Post(
            kind=PostKind.SOURCE, original_text="orig", rewritten_text="final text",
            status=PostStatus.POSTED, **kwargs,
        )
        session.add(post)
        session.flush()
        pid = post.id
    with session_scope() as session:
        return session.get(Post, pid)


def test_export_posts_includes_only_posted_status():
    _clean()
    posted = _make_posted_post(posted_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
    with session_scope() as session:
        session.add(Post(kind=PostKind.SOURCE, original_text="x", status=PostStatus.NEW))

    rows = export_posts()

    assert len(rows) == 1
    assert rows[0]["id"] == posted.id
    _clean()


def test_export_posts_filters_by_date_range():
    _clean()
    _make_posted_post(posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    mid = _make_posted_post(posted_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
    _make_posted_post(posted_at=datetime(2026, 12, 1, tzinfo=timezone.utc))

    rows = export_posts(
        since=datetime(2026, 3, 1, tzinfo=timezone.utc),
        until=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    assert [r["id"] for r in rows] == [mid.id]
    _clean()


def test_export_posts_includes_targets_and_latest_stat():
    _clean()
    post = _make_posted_post(posted_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
    post_targets_repo.record_targets(post.id, [(-100111, 42, None)])
    with session_scope() as session:
        session.add(PostStat(post_id=post.id, view_count=10, captured_at=datetime(2026, 6, 2, tzinfo=timezone.utc)))
        session.add(PostStat(post_id=post.id, view_count=50, captured_at=datetime(2026, 6, 3, tzinfo=timezone.utc)))

    rows = export_posts()

    assert rows[0]["targets"] == [{"chat_id": -100111, "message_id": 42, "ok": True}]
    assert rows[0]["view_count"] == 50  # последний снимок, не первый
    _clean()


def test_export_posts_json_round_trips():
    _clean()
    _make_posted_post(posted_at=datetime(2026, 6, 1, tzinfo=timezone.utc), source_link="https://x.example")

    parsed = json.loads(export_posts_json())

    assert len(parsed) == 1
    assert parsed[0]["source_link"] == "https://x.example"
    assert parsed[0]["rewritten_text"] == "final text"
    _clean()


def test_export_posts_csv_has_header_and_row():
    _clean()
    post = _make_posted_post(posted_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
    post_targets_repo.record_targets(post.id, [(-100111, 42, None)])

    csv_text = export_posts_csv()
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = list(reader)

    assert len(rows) == 1
    assert rows[0]["id"] == str(post.id)
    assert rows[0]["targets"] == "-100111:42"
    _clean()


def test_export_posts_empty_when_no_posted_posts():
    _clean()
    assert export_posts() == []
    assert json.loads(export_posts_json()) == []
    reader = csv.DictReader(io.StringIO(export_posts_csv()))
    assert list(reader) == []


def test_export_posts_csv_joins_multiple_targets():
    _clean()
    post = _make_posted_post(posted_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
    post_targets_repo.record_targets(post.id, [(-100111, 42, None), (-100222, 7, None)])

    reader = csv.DictReader(io.StringIO(export_posts_csv()))
    rows = list(reader)

    assert rows[0]["targets"] == "-100111:42; -100222:7"
    _clean()


def _make_posted_post_with_text(original_text: str, source_link: str | None = None) -> Post:
    with session_scope() as session:
        post = Post(
            kind=PostKind.SOURCE, original_text=original_text, rewritten_text="final text",
            status=PostStatus.POSTED, posted_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            source_link=source_link,
        )
        session.add(post)
        session.flush()
        pid = post.id
    with session_scope() as session:
        return session.get(Post, pid)


def test_export_posts_csv_escapes_formula_injection():
    """Аудит: original_text приходит из чужого спарсенного канала — строка,
    начинающаяся с `=`/`+`/`-`/`@`, интерпретируется Excel/Sheets как формула
    (например `=HYPERLINK(...)`). Ведущий апостроф обязан это гасить."""
    _clean()
    _make_posted_post_with_text(
        original_text='=HYPERLINK("http://evil.example","click")',
        source_link="=cmd|'/c calc'!A1",
    )

    reader = csv.DictReader(io.StringIO(export_posts_csv()))
    row = next(reader)

    assert row["original_text"].startswith("'=")
    assert row["source_link"].startswith("'=")
    _clean()


def test_export_posts_csv_does_not_prefix_normal_text():
    _clean()
    _make_posted_post_with_text(original_text="обычный текст поста")

    reader = csv.DictReader(io.StringIO(export_posts_csv()))
    row = next(reader)

    assert row["original_text"] == "обычный текст поста"
    _clean()


def test_export_posts_csv_does_not_escape_negative_chat_id_in_targets():
    """Аудит: `targets` — системное поле (не пользовательский текст), не
    должно эскейпиться как формула, даже начинаясь с "-" (отрицательный
    chat_id) — иначе "-100111:42" превратилось бы в "'-100111:42",
    испортив данные без реальной защиты (это не источник инъекции)."""
    _clean()
    post = _make_posted_post(posted_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
    post_targets_repo.record_targets(post.id, [(-100111, 42, None)])

    reader = csv.DictReader(io.StringIO(export_posts_csv()))
    row = next(reader)

    assert row["targets"] == "-100111:42"
    _clean()
