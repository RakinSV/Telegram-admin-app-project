"""Тесты выбора стиль-профиля рерайта (F15)."""

from tg_repost.rewriter.client import (
    KNOWN_STYLES,
    prompt_exists,
    resolve_style_prompt,
)


def test_known_styles_have_prompts():
    for style in KNOWN_STYLES:
        assert prompt_exists(style), f"нет файла промпта для стиля {style}"


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
