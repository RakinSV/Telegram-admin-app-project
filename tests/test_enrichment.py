"""Тесты обогащения источниками (F16): чистые хелперы."""

from tg_repost.enrichment.enricher import (
    detect_language,
    format_sources_block,
    parse_indices,
)
from tg_repost.enrichment.search import SearchResult


def test_detect_language_ru():
    assert detect_language("Привет мир") == "ru"


def test_detect_language_en():
    assert detect_language("Hello world") == "en"


def test_detect_language_empty_is_en():
    assert detect_language("") == "en"


def test_parse_indices_basic():
    assert parse_indices("1, 3, 5", total=8) == [0, 2, 4]


def test_parse_indices_net_means_empty():
    assert parse_indices("НЕТ", total=5) == []
    assert parse_indices("нет релевантных", total=5) == []


def test_parse_indices_filters_out_of_range():
    assert parse_indices("2, 99, 4", total=5) == [1, 3]


def test_parse_indices_dedup():
    assert parse_indices("1, 1, 2", total=5) == [0, 1]


def test_parse_indices_empty_answer():
    assert parse_indices("", total=5) == []


def test_format_sources_block_empty():
    assert format_sources_block([]) == ""


def test_format_sources_block_splits_languages():
    selected = [
        SearchResult(title="Новость дня", url="https://ru.example/1", description="текст"),
        SearchResult(title="Breaking news", url="https://en.example/2", description="text"),
    ]
    block = format_sources_block(selected)
    assert "Источники" in block
    assert "https://ru.example/1" in block
    assert "https://en.example/2" in block
    assert "Рус." in block
    assert "Англ." in block


def test_format_sources_block_only_ru():
    selected = [SearchResult(title="Заголовок", url="https://ru.example/x")]
    block = format_sources_block(selected)
    assert "Рус." in block
    assert "Англ." not in block
