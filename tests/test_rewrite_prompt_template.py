"""Тесты выбора шаблона промпта рерайта и сборки финального промпта.

ВСЕ пять стиль-профилей (F15) редактируются из /settings — раньше поле было
только у "default", а news/opinion/instruction/humor читались напрямую из
файлов: источник со `style_profile="news"` молча игнорировал промпт,
отредактированный владельцем в админке. Файл `prompts/<стиль>.txt` остаётся
запасным вариантом, если поле очистили пустым.

См. rewriter/client.py::resolve_rewrite_template / build_rewrite_prompt.
"""

import pytest

from tg_repost.config import get_settings, invalidate_settings_cache
from tg_repost.db.models import AppSetting
from tg_repost.db.session import session_scope
from tg_repost.rewriter.client import (
    _STYLE_SETTING_FIELDS,
    build_rewrite_prompt,
    load_prompt,
    resolve_rewrite_template,
)
from tg_repost.webui import settings_store

_PROMPT_KEYS = (
    *_STYLE_SETTING_FIELDS.values(),
    "rewrite_humanize_enabled",
    "rewrite_humanize_instructions",
)


@pytest.fixture(autouse=True)
def _clean_rewrite_prompt_settings():
    def _wipe() -> None:
        with session_scope() as session:
            session.query(AppSetting).filter(AppSetting.key.in_(_PROMPT_KEYS)).delete(
                synchronize_session=False,
            )
        invalidate_settings_cache()

    _wipe()
    yield
    _wipe()


def test_default_style_uses_settings_template_by_default():
    # Без оверлея в БД — используется дефолт из Settings (не пустой);
    # resolve_rewrite_template дополнительно .strip()-ает результат.
    assert resolve_rewrite_template("default") == get_settings().rewrite_prompt_template.strip()


def test_default_style_picks_up_admin_edited_template():
    custom = "Кастомный промпт: {post_text} / {link_content}"
    settings_store.save_setting("rewrite_prompt_template", custom, "str")
    assert resolve_rewrite_template("default") == custom


def test_default_style_falls_back_to_file_when_template_cleared_blank():
    settings_store.save_setting("rewrite_prompt_template", "   ", "str")
    assert resolve_rewrite_template("default") == load_prompt("default")


@pytest.mark.parametrize("style", ["news", "opinion", "instruction", "humor"])
def test_named_style_picks_up_admin_edited_template(style):
    """Регрессия: раньше именованные стили читались ТОЛЬКО из файла, и правка
    промпта в админке для них молча не применялась."""
    custom = f"Кастомный промпт {style}: {{post_text}} / {{link_content}}"
    settings_store.save_setting(_STYLE_SETTING_FIELDS[style], custom, "str")
    assert resolve_rewrite_template(style) == custom


@pytest.mark.parametrize("style", ["news", "opinion", "instruction", "humor"])
def test_named_style_falls_back_to_file_when_cleared_blank(style):
    settings_store.save_setting(_STYLE_SETTING_FIELDS[style], "   ", "str")
    assert resolve_rewrite_template(style) == load_prompt(style)


def test_editing_one_style_does_not_leak_into_another():
    settings_store.save_setting("rewrite_prompt_news", "только для news", "str")
    assert resolve_rewrite_template("news") == "только для news"
    assert resolve_rewrite_template("humor") != "только для news"


@pytest.mark.parametrize("style", ["default", "news", "opinion", "instruction", "humor"])
def test_every_style_default_has_both_placeholders(style):
    # Оба плейсхолдера обязаны быть в дефолте КАЖДОГО стиля — иначе .format()
    # молча проигнорирует один из источников контекста, и рерайт «news»
    # снова начнёт синонимайзить тизер, не видя текста статьи.
    template = resolve_rewrite_template(style)
    assert "{post_text}" in template
    assert "{link_content}" in template


# --- анти-ИИ блок ---


def test_humanize_block_appended_to_prompt_when_enabled():
    settings_store.save_setting("rewrite_humanize_enabled", True, "bool")
    settings_store.save_setting("rewrite_humanize_instructions", "НЕ ПИШИ КАК БОТ", "str")
    prompt = build_rewrite_prompt("default", "исходный пост", "текст статьи")
    assert prompt.endswith("НЕ ПИШИ КАК БОТ")
    assert "исходный пост" in prompt
    assert "текст статьи" in prompt


def test_humanize_block_omitted_when_disabled():
    settings_store.save_setting("rewrite_humanize_enabled", False, "bool")
    settings_store.save_setting("rewrite_humanize_instructions", "НЕ ПИШИ КАК БОТ", "str")
    assert "НЕ ПИШИ КАК БОТ" not in build_rewrite_prompt("default", "пост")


def test_humanize_block_omitted_when_instructions_blank():
    settings_store.save_setting("rewrite_humanize_enabled", True, "bool")
    settings_store.save_setting("rewrite_humanize_instructions", "   ", "str")
    prompt = build_rewrite_prompt("default", "пост")
    assert prompt == prompt.rstrip()  # без болтающегося хвоста из пустых строк


@pytest.mark.parametrize("style", ["default", "news", "opinion", "instruction", "humor"])
def test_humanize_block_applies_to_every_style(style):
    """Правило «не как нейросеть» одно на все стили — иначе владелец,
    настроивший его один раз, получал бы машинный текст на источниках с
    другим стиль-профилем."""
    settings_store.save_setting("rewrite_humanize_enabled", True, "bool")
    settings_store.save_setting("rewrite_humanize_instructions", "МАРКЕР-АНТИИИ", "str")
    assert "МАРКЕР-АНТИИИ" in build_rewrite_prompt(style, "пост")


def test_default_humanize_instructions_are_not_empty():
    # Пустой дефолт означал бы, что галочка включена, а эффекта нет.
    assert get_settings().rewrite_humanize_instructions.strip()
