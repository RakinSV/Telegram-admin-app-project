"""Тесты выбора стиль-профиля рерайта (F15)."""

from tg_repost.config import Settings
from tg_repost.rewriter.client import (
    _STYLE_SETTING_FIELDS,
    KNOWN_STYLES,
    prompt_exists,
    resolve_style_prompt,
)


def test_known_styles_have_prompts():
    for style in KNOWN_STYLES:
        assert prompt_exists(style), f"нет файла промпта для стиля {style}"


def test_every_known_style_has_an_editable_setting_field():
    """Регресс на исходную дыру: стиль, предлагаемый в UI, но без своего поля
    настройки, молча работал бы по жёстко зашитому файлу — правки владельца в
    админке для него бы не применялись, и понять это из интерфейса невозможно."""
    assert set(KNOWN_STYLES) == set(_STYLE_SETTING_FIELDS)


def test_every_style_setting_field_exists_on_settings():
    """Опечатка в имени поля дала бы тихий откат на файл через getattr(...,
    default) — стиль снова стал бы нередактируемым, но уже незаметно."""
    for style, field in _STYLE_SETTING_FIELDS.items():
        assert field in Settings.model_fields, f"нет поля Settings.{field} (стиль {style})"


def test_unknown_style_falls_back_to_default():
    assert resolve_style_prompt("nonexistent-style") == "default"


def test_known_style_resolves_to_itself():
    assert resolve_style_prompt("news") == "news"
    assert resolve_style_prompt("humor") == "humor"


def test_none_style_resolves_to_default():
    assert resolve_style_prompt(None) == "default"


def test_prompt_exists_false_for_garbage():
    assert not prompt_exists("")
    assert not prompt_exists("../secrets")
