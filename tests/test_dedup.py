"""Тесты нормализации и хэш-дедупликации (F04)."""

from tg_repost.dedup.hash_dedup import content_hash, normalize_text


def test_normalize_lowercases_and_collapses_spaces():
    assert normalize_text("Привет   МИР") == "привет мир"


def test_normalize_strips_urls():
    assert normalize_text("текст https://example.com/x?a=1 ещё") == "текст ещё"


def test_normalize_strips_punctuation():
    assert normalize_text("Да! Нет? Точно...") == "да нет точно"


def test_identical_text_same_hash():
    assert content_hash("Один и тот же пост") == content_hash("Один и тот же пост")


def test_case_and_space_insensitive_hash():
    assert content_hash("Новость дня") == content_hash("  новость   ДНЯ  ")


def test_punctuation_insensitive_hash():
    assert content_hash("Привет, мир!") == content_hash("привет мир")


def test_different_text_different_hash():
    assert content_hash("Пост А") != content_hash("Пост Б")


def test_hash_is_sha256_hex():
    digest = content_hash("любой текст")
    assert len(digest) == 64
    int(digest, 16)  # валидный hex
