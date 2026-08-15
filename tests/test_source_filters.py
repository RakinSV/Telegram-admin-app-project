"""Фильтры на уровне источника (F54).

Главное, что защищаем — АСИММЕТРИЮ двух списков. Стоп-слова складываются с
глобальными, обязательные их замещают. Это выглядит непоследовательно ровно
до тех пор, пока не вспомнишь, как работает сам фильтр: стоп-слово отсекает
по любому совпадению (объединение = строже), а обязательные срабатывают по
«хотя бы одному» (объединение = слабее). Если кто-то «выровняет» поведение,
эти тесты обязаны упасть.
"""

from __future__ import annotations

import pytest

from tg_repost import ingest
from tg_repost.db.models import Post, PostStatus, Source
from tg_repost.db.session import session_scope
from tg_repost.filtering import parse_words, resolve_filters

GLOBAL_STOP = ["казино", "ставки"]
GLOBAL_REQUIRED = ["уязвимость", "cve"]


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(Post).delete()
            session.query(Source).filter(
                Source.channel_username.like("f54_%")
            ).delete(synchronize_session=False)

    _wipe()
    yield
    _wipe()


def _make_source(stop: str | None = None, required: str | None = None) -> int:
    with session_scope() as session:
        source = Source(
            channel_username=f"f54_{id(object()):x}",
            filter_stop_words=stop,
            filter_required_words=required,
        )
        session.add(source)
        session.flush()
        return source.id


# --- разбор CSV ---


def test_parse_none_stays_none():
    """`None` — «источник ничего не переопределяет», пустой список — «явно пусто».

    Их нельзя схлопывать: для обязательных слов пустой список СНИМАЕТ
    требование, а None велит взять глобальное.
    """
    assert parse_words(None) is None


def test_parse_empty_string_is_empty_list():
    assert parse_words("") == []
    assert parse_words("  ,  , ") == []


def test_parse_trims_and_lowercases():
    assert parse_words(" Казино , СТАВКИ ") == ["казино", "ставки"]


# --- асимметрия списков ---


def test_source_stop_words_add_to_global():
    """Стоп-слова источника НЕ отменяют глобальные, а добавляются к ним.

    Иначе владелец, задав источнику одно своё стоп-слово, молча снял бы с
    него всю глобальную защиту и узнал бы об этом по мусору в ленте.
    """
    source = Source(channel_username="x", filter_stop_words="реклама")
    stop, required = resolve_filters(source, GLOBAL_STOP, GLOBAL_REQUIRED)

    assert "реклама" in stop
    assert "казино" in stop and "ставки" in stop


def test_source_required_words_replace_global():
    """Обязательные слова источника ЗАМЕЩАЮТ глобальные.

    Объединение здесь ослабило бы фильтр: срабатывает «хотя бы одно», и чем
    длиннее список, тем больше проходит. Лента про крипту должна требовать
    свою тему, а не пропускать ещё и посты про CVE.
    """
    source = Source(channel_username="x", filter_required_words="крипта")
    stop, required = resolve_filters(source, GLOBAL_STOP, GLOBAL_REQUIRED)

    assert required == ["крипта"]
    assert "уязвимость" not in required


def test_empty_required_removes_requirement_entirely():
    """Явно пустой список обязательных слов снимает требование.

    Это и есть «спокойной ленте мягкие правила»: берём из неё всё подряд,
    не требуя тематических слов.
    """
    source = Source(channel_username="x", filter_required_words="")
    _, required = resolve_filters(source, GLOBAL_STOP, GLOBAL_REQUIRED)

    assert required == []


def test_null_fields_fall_back_to_global():
    source = Source(channel_username="x")
    stop, required = resolve_filters(source, GLOBAL_STOP, GLOBAL_REQUIRED)

    assert stop == GLOBAL_STOP
    assert required == GLOBAL_REQUIRED


def test_no_source_falls_back_to_global():
    stop, required = resolve_filters(None, GLOBAL_STOP, GLOBAL_REQUIRED)

    assert stop == GLOBAL_STOP
    assert required == GLOBAL_REQUIRED


# --- сквозь приём ---


def _ingest(source_id: int, text: str):
    with session_scope() as session:
        return ingest.ingest_post(
            session, source_id=source_id, text=text, source_link=None,
        )


def test_source_stop_word_filters_post_out(monkeypatch):
    from tg_repost.config import get_settings

    monkeypatch.setattr(get_settings(), "filter_stop_words", [], raising=False)
    monkeypatch.setattr(get_settings(), "filter_required_words", [], raising=False)

    source_id = _make_source(stop="партнёрский материал")
    result = _ingest(source_id, "Это партнёрский материал про новый продукт")

    assert result.status == PostStatus.FILTERED_OUT
    assert result.reason is not None
    assert "партнёрский материал" in result.reason


def test_post_passes_when_source_words_do_not_match(monkeypatch):
    from tg_repost.config import get_settings

    monkeypatch.setattr(get_settings(), "filter_stop_words", [], raising=False)
    monkeypatch.setattr(get_settings(), "filter_required_words", [], raising=False)

    source_id = _make_source(stop="партнёрский материал")
    result = _ingest(source_id, "Обычная новость без рекламы")

    assert result.status == PostStatus.NEW


def test_global_stop_still_applies_to_source_with_own_list(monkeypatch):
    """Ключевой сквозной тест асимметрии: своё стоп-слово не отменило общее."""
    from tg_repost.config import get_settings

    monkeypatch.setattr(get_settings(), "filter_stop_words", ["казино"], raising=False)
    monkeypatch.setattr(get_settings(), "filter_required_words", [], raising=False)

    source_id = _make_source(stop="реклама")
    result = _ingest(source_id, "Новое казино открылось в городе")

    assert result.status == PostStatus.FILTERED_OUT
    assert result.reason is not None
    assert "казино" in result.reason


def test_source_required_word_gates_topic(monkeypatch):
    from tg_repost.config import get_settings

    monkeypatch.setattr(get_settings(), "filter_stop_words", [], raising=False)
    monkeypatch.setattr(get_settings(), "filter_required_words", [], raising=False)

    source_id = _make_source(required="крипта,биткоин")

    off_topic = _ingest(source_id, "Прогноз погоды на завтра")
    assert off_topic.status == PostStatus.FILTERED_OUT

    on_topic = _ingest(source_id, "Курс биткоин обновил максимум")
    assert on_topic.status == PostStatus.NEW


def test_source_bypasses_global_required(monkeypatch):
    """Спокойная лента без тематического требования проходит,
    хотя глобально требование задано."""
    from tg_repost.config import get_settings

    monkeypatch.setattr(get_settings(), "filter_stop_words", [], raising=False)
    monkeypatch.setattr(
        get_settings(), "filter_required_words", ["уязвимость"], raising=False,
    )

    source_id = _make_source(required="")
    result = _ingest(source_id, "Просто новость ни о чём")

    assert result.status == PostStatus.NEW


# --- сохранение из админки ---


def test_repo_saves_and_clears_filters():
    from tg_repost import sources_repo

    source_id = _make_source()

    sources_repo.set_source_filters(
        source_id, stop_words="реклама,промо", required_words="крипта",
    )
    with session_scope() as session:
        row = session.get(Source, source_id)
        assert row is not None
        assert row.filter_stop_words == "реклама,промо"
        assert row.filter_required_words == "крипта"

    sources_repo.set_source_filters(source_id, stop_words=None, required_words=None)
    with session_scope() as session:
        row = session.get(Source, source_id)
        assert row is not None
        assert row.filter_stop_words is None
        assert row.filter_required_words is None


def test_repo_distinguishes_empty_from_none_for_required():
    """Пустая строка и None должны сохраняться РАЗНЫМИ значениями.

    Если репозиторий схлопнет «» в None, галочка «переопределить» с пустым
    полем перестанет работать: вместо «требований нет» источник молча
    вернётся к глобальному списку.
    """
    from tg_repost import sources_repo

    source_id = _make_source()
    sources_repo.set_source_filters(source_id, stop_words=None, required_words="")

    with session_scope() as session:
        row = session.get(Source, source_id)
        assert row is not None
        assert row.filter_required_words == ""
        assert row.filter_required_words is not None

    _, required = resolve_filters(row, GLOBAL_STOP, GLOBAL_REQUIRED)
    assert required == []


# --- экономия на эмбеддингах ---


async def test_embedding_not_computed_for_source_filtered_post(monkeypatch):
    """За эмбеддинг поста, который отсеет СОБСТВЕННОЕ стоп-слово источника,
    платить не должны.

    Раньше `compute_embedding` знал только глобальные списки — то есть ровно
    для тех лент, ради которых делалась F54, экономия не работала бы.
    """
    from tg_repost.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "semantic_dedup_enabled", True, raising=False)
    monkeypatch.setattr(settings, "filter_stop_words", [], raising=False)
    monkeypatch.setattr(settings, "filter_required_words", [], raising=False)

    called = False

    def _boom(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("эмбеддинг не должен считаться для отсеянного поста")

    monkeypatch.setattr("tg_repost.rewriter.client.get_rewriter", _boom, raising=False)

    source_id = _make_source(stop="партнёрский материал")
    result = await ingest.compute_embedding(
        "Это партнёрский материал", source_id=source_id,
    )

    assert result is None
    assert called is False
