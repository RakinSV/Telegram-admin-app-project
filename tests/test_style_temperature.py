"""Своя температура у каждого стиль-профиля (найдено 2026-08-23).

ПОЧЕМУ «ПИШЕТ ХРЕНЬ». Промпты в системе подробные и прямо запрещают
выдумывать числа. Но температура была ОДНА на все стиль-профили, и стояла
0.8 — «пиши творчески». Замер на стенде: в новость про уязвимость eID модель
дописала «учётные записи двух миллионов граждан», числа, которого в источнике
нет вовсе. Промпт с настройкой не спорит — он проигрывает.

Одним числом это не выражается: новость и инструкция живут фактами, а мнение
и юмор без свободы становятся пересказом. Поэтому у профиля может быть своя
температура, а пусто означает «общая».

ПОЧЕМУ ПУСТО, А НЕ НОЛЬ. Ноль — законное значение «отвечай детерминированно».
Если бы пустое поле превращалось в ноль (как это делает обычный числовой тип
в формах), включение настройки молча замораживало бы модель.
"""

from __future__ import annotations

import pytest

from tg_repost.config import invalidate_settings_cache
from tg_repost.rewriter.client import temperature_for_style
from tg_repost.webui.form_utils import coerce_form_value


@pytest.fixture
def base(monkeypatch):
    monkeypatch.setenv("REWRITE_TEMPERATURE", "0.8")
    for name in ("NEWS", "OPINION", "INSTRUCTION", "HUMOR"):
        monkeypatch.delenv(f"REWRITE_TEMPERATURE_{name}", raising=False)
    invalidate_settings_cache()
    yield monkeypatch
    invalidate_settings_cache()


# --- наследование ---


def test_all_styles_inherit_the_shared_temperature(base):
    """Ничего не заполнено — поведение ровно прежнее."""
    for style in ("default", "news", "opinion", "instruction", "humor"):
        assert temperature_for_style(style) == 0.8, style


def test_news_can_be_made_factual(base):
    """ГЛАВНЫЙ СЛУЧАЙ: новость перестаёт выдумывать числа."""
    base.setenv("REWRITE_TEMPERATURE_NEWS", "0.3")
    invalidate_settings_cache()

    assert temperature_for_style("news") == 0.3
    # Остальные не задеты.
    assert temperature_for_style("humor") == 0.8
    assert temperature_for_style("default") == 0.8


def test_humor_can_be_made_free(base):
    base.setenv("REWRITE_TEMPERATURE_HUMOR", "1.0")
    invalidate_settings_cache()

    assert temperature_for_style("humor") == 1.0
    assert temperature_for_style("news") == 0.8


def test_zero_is_a_real_temperature_not_an_empty_field(base):
    """Ноль означает «отвечай детерминированно», а не «наследуй общую».

    Если их спутать, включение настройки молча заморозит модель — и понять
    это по интерфейсу будет невозможно.
    """
    base.setenv("REWRITE_TEMPERATURE_NEWS", "0")
    invalidate_settings_cache()

    assert temperature_for_style("news") == 0.0, (
        "ноль принят за пустое поле — профиль вернулся к общей температуре"
    )


def test_default_profile_has_no_own_temperature(base):
    """`default` — это и есть «общий» профиль, своя настройка ему не нужна."""
    from tg_repost.rewriter.client import _STYLE_TEMPERATURE_FIELDS

    assert "default" not in _STYLE_TEMPERATURE_FIELDS


# --- разбор поля формы ---


def test_empty_field_means_inherit_not_zero():
    assert coerce_form_value("optional_float", "") is None
    assert coerce_form_value("optional_float", "   ") is None
    assert coerce_form_value("optional_float", None) is None


def test_explicit_zero_survives_the_form():
    assert coerce_form_value("optional_float", "0") == 0.0
    assert coerce_form_value("optional_float", "0.35") == 0.35


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf"])
def test_nan_and_infinity_are_refused(raw):
    with pytest.raises(ValueError):
        coerce_form_value("optional_float", raw)


# --- проводка до реального вызова ---


@pytest.mark.asyncio
async def test_rewrite_really_uses_the_style_temperature(base):
    """ПРОВЕРКА ПУТИ, А НЕ ФУНКЦИИ: настройка бесполезна, если до вызова она
    не доходит. Смотрим, с какой температурой ушёл запрос."""
    base.setenv("REWRITE_TEMPERATURE_NEWS", "0.25")
    base.setenv("REWRITE_PROMPT_NEWS", "Новость: {post_text} {link_content}")
    invalidate_settings_cache()

    from tg_repost.rewriter import client as client_module

    asked: list[float] = []

    class FakeCompletions:
        async def create(self, *, model, messages, temperature):
            asked.append(temperature)
            usage = type("U", (), {"prompt_tokens": 1, "completion_tokens": 1})()
            message = type("M", (), {"content": "готовый текст"})()
            choice = type("C", (), {"message": message})()
            return type("R", (), {"choices": [choice], "usage": usage})()

    client = client_module.RewriterClient.__new__(client_module.RewriterClient)
    client._client = type("Cl", (), {"chat": type("Ch", (), {
        "completions": FakeCompletions()})()})()
    client._model = "модель"

    await client.rewrite("исходный текст", prompt_name="news")

    assert asked == [0.25], (
        f"запрос ушёл с температурой {asked} — настройка профиля до вызова "
        f"не доходит"
    )


# --- достижимость ---


def test_temperature_fields_are_on_the_settings_page():
    from tg_repost.webui.settings_store import SETTINGS_GROUPS

    names = {f.name for group in SETTINGS_GROUPS for f in group.fields}
    for style in ("news", "opinion", "instruction", "humor"):
        assert f"rewrite_temperature_{style}" in names, style
