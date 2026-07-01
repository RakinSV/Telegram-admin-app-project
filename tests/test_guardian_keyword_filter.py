"""Тесты нормализации текста и фильтра стоп-слов Guardian (G03)."""

from guardian.db.models import StopWord
from guardian.db.session import session_scope
from guardian.filters.keyword_filter import KeywordFilter, normalize


def _clear_stop_words() -> None:
    with session_scope() as session:
        session.query(StopWord).delete()


def test_normalize_lowercases_and_collapses_spaces():
    assert normalize("Купить   СЕЙЧАС") == "купить сейчас"


def test_normalize_replaces_latin_homoglyphs():
    assert normalize("зaрaботок") == "заработок"  # латинские a вместо кириллических а


def test_normalize_strips_letter_separators():
    assert normalize("к-у-п-и-т-ь") == "купить"


def test_normalize_strips_zero_width_chars():
    text = "заработок" + chr(0x200B) + "тест"
    assert normalize(text) == "заработоктест"


def test_normalize_empty_string():
    assert normalize("") == ""


def test_keyword_filter_no_words_loaded_never_matches():
    _clear_stop_words()
    kf = KeywordFilter()
    with session_scope() as session:
        kf.reload(session)
    assert kf.check("любой текст") == (False, None)


def test_keyword_filter_matches_stop_word():
    _clear_stop_words()
    with session_scope() as session:
        session.add(StopWord(word="казино", added_by="test"))
    kf = KeywordFilter()
    with session_scope() as session:
        kf.reload(session)
    hit, word = kf.check("Заходи в наше КАЗИНО прямо сейчас")
    assert hit is True
    assert word == "казино"


def test_keyword_filter_matches_evasion_attempt():
    _clear_stop_words()
    with session_scope() as session:
        session.add(StopWord(word="заработок", added_by="test"))
    kf = KeywordFilter()
    with session_scope() as session:
        kf.reload(session)
    hit, word = kf.check("з-a-р-a-б-о-т-о-к прямо сейчас")
    assert hit is True
    assert word == "заработок"


def test_keyword_filter_no_match_on_unrelated_text():
    _clear_stop_words()
    with session_scope() as session:
        session.add(StopWord(word="казино", added_by="test"))
    kf = KeywordFilter()
    with session_scope() as session:
        kf.reload(session)
    assert kf.check("Обычное сообщение про погоду") == (False, None)


def test_keyword_filter_empty_text_no_match():
    _clear_stop_words()
    with session_scope() as session:
        session.add(StopWord(word="казино", added_by="test"))
    kf = KeywordFilter()
    with session_scope() as session:
        kf.reload(session)
    assert kf.check("") == (False, None)
