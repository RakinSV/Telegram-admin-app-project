"""Тесты разбора слотов публикации (F11) и CSV целей (F12)."""

from tg_repost.db.models import parse_chat_ids_csv
from tg_repost.scheduler.posting import parse_slot


def test_parse_slot_valid():
    assert parse_slot("10:00") == (10, 0)
    assert parse_slot("23:59") == (23, 59)
    assert parse_slot("00:00") == (0, 0)


def test_parse_slot_invalid():
    assert parse_slot("24:00") is None
    assert parse_slot("10:60") is None
    assert parse_slot("abc") is None
    assert parse_slot("10") is None
    assert parse_slot("") is None


def test_parse_chat_ids_csv():
    assert parse_chat_ids_csv("-100123, -100456") == [-100123, -100456]
    assert parse_chat_ids_csv("") == []
    assert parse_chat_ids_csv(None) == []


def test_parse_chat_ids_csv_skips_garbage():
    assert parse_chat_ids_csv("-100123, abc, -100456") == [-100123, -100456]
