"""Тесты выбора шаблона промпта рерайта (F16-доп.): стиль "default" читается
из редактируемой в /settings настройки, остальные стили — по-прежнему из
файлов prompts/*.txt (F15), см. rewriter/client.py::resolve_rewrite_template."""

import pytest

from tg_repost.config import get_settings, invalidate_settings_cache
from tg_repost.db.models import AppSetting
from tg_repost.db.session import session_scope
from tg_repost.rewriter.client import load_prompt, resolve_rewrite_template
from tg_repost.webui import settings_store


@pytest.fixture(autouse=True)
def _clean_rewrite_prompt_setting():
    with session_scope() as session:
        session.query(AppSetting).filter(AppSetting.key == "rewrite_prompt_template").delete()
    invalidate_settings_cache()
    yield
    with session_scope() as session:
        session.query(AppSetting).filter(AppSetting.key == "rewrite_prompt_template").delete()
    invalidate_settings_cache()


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


def test_named_style_still_reads_from_file_regardless_of_setting():
    settings_store.save_setting("rewrite_prompt_template", "не должно повлиять на news", "str")
    assert resolve_rewrite_template("news") == load_prompt("news")


def test_resolved_template_has_post_text_and_link_content_placeholders():
    # Оба плейсхолдера обязаны быть в дефолте — иначе .format() в rewrite()
    # молча проигнорирует один из источников контекста.
    template = resolve_rewrite_template("default")
    assert "{post_text}" in template
    assert "{link_content}" in template
