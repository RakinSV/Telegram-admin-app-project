"""Тесты фильтра ключевых слов (F03)."""

from tg_repost.filtering import check_keywords


def test_passes_without_filters():
    result = check_keywords("любой текст", [], [])
    assert result.passed


def test_stop_word_blocks():
    result = check_keywords("это реклама казино", ["казино"], [])
    assert not result.passed
    assert "казино" in result.reason


def test_required_word_present_passes():
    result = check_keywords("новость про python", [], ["python", "rust"])
    assert result.passed


def test_required_word_absent_blocks():
    result = check_keywords("новость про погоду", [], ["python", "rust"])
    assert not result.passed


def test_stop_word_has_priority_over_required():
    result = check_keywords("python и казино", ["казино"], ["python"])
    assert not result.passed
    assert "казино" in result.reason


def test_case_insensitive():
    result = check_keywords("Большое КАЗИНО", ["казино"], [])
    assert not result.passed
