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


# --- качество дефолтных промптов ---


@pytest.mark.parametrize("style", ["default", "news", "opinion", "instruction", "humor"])
def test_style_setting_default_matches_prompt_file(style):
    """Единый источник истины для дефолтов — файлы `prompts/*.txt`.

    Регрессия: у стиля "default" дефолт дублировался ещё и литералом в
    config.py, и две копии успели разойтись — в файле остался старый слабый
    текст. Очистка поля в админке откатывала пользователя на СТАРУЮ редакцию,
    и заметить это было нечем.
    """
    field = _STYLE_SETTING_FIELDS[style]
    assert getattr(get_settings(), field).strip() == load_prompt(style).strip()


@pytest.mark.parametrize("style", ["default", "news", "opinion", "instruction", "humor"])
def test_material_comes_before_instructions_in_prompt(style):
    """Материал сверху, задача снизу: со статьёй на несколько тысяч символов
    инструкции, стоящие ПЕРЕД ней, размываются — модель хуже держит правила.
    Раньше все шаблоны были устроены наоборот."""
    template = resolve_rewrite_template(style)
    material_end = template.index("</статья_по_ссылке>")
    assert template.index("{post_text}") < material_end
    assert template.index("{link_content}") < material_end
    # Финальный контракт ответа — в самом конце, последним, что видит модель.
    assert "ОТВЕТ" in template[material_end:]
    assert template.rstrip().endswith(("»", ".", "»."))


@pytest.mark.parametrize("style", ["default", "news", "opinion", "instruction", "humor"])
def test_prompt_states_telegram_length_budget(style):
    """Лимит подписи к медиа в Telegram — 1024 символа. Без явного бюджета
    «полный рерайт по статье» стабильно вылезал за него, и пост разрывался
    на подпись и отдельное сообщение."""
    template = resolve_rewrite_template(style)
    assert "600" in template and "900" in template
    assert "1024" in template


@pytest.mark.parametrize("style", ["default", "news", "opinion", "instruction", "humor"])
def test_prompt_handles_empty_article_block_explicitly(style):
    """Пустой блок статьи — штатная ситуация (ссылки не было / сайт не отдал
    текст). Модель не должна ни оправдываться, ни выдумывать недостающее."""
    template = resolve_rewrite_template(style)
    assert "пустой" in template
    assert "не выдумывай" in template.lower() or "не добавляй" in template.lower()


@pytest.mark.parametrize("style", ["default", "news", "opinion", "instruction", "humor"])
def test_prompt_forbids_preamble_in_output(style):
    template = resolve_rewrite_template(style)
    assert "ТОЛЬКО текст поста" in template


@pytest.mark.parametrize("style", ["default", "news", "opinion", "instruction", "humor"])
def test_prompt_requires_keeping_repo_links(style):
    """Для поста про инструмент ссылка на репозиторий и есть весь смысл.
    Правило «не добавляй ссылок» без парного «эти — сохрани» модель читает
    как разрешение выбросить и исходную ссылку тоже."""
    template = resolve_rewrite_template(style)
    assert "GitHub" in template
    assert "СОХРАНИ" in template


@pytest.mark.parametrize("style", ["default", "news", "opinion", "instruction", "humor"])
def test_prompt_strips_channel_promo_links(style):
    """Ссылка «подпишись на нас» из чужого поста — бесплатная реклама
    канала-источника в своём канале. Раньше правило её не запрещало, и
    сохранится она или нет решала модель."""
    template = resolve_rewrite_template(style)
    assert "t.me" in template
    assert "УБЕРИ" in template


@pytest.mark.parametrize("style", ["default", "news", "opinion", "instruction", "humor"])
def test_link_rules_are_one_contiguous_block(style):
    """Три правила про ссылки должны читаться как один список: разнесённые
    по разным местам промпта, «сохрани репозиторий» и «убери остальные»
    выглядят как противоречие."""
    template = resolve_rewrite_template(style)
    keep = template.index("СОХРАНИ")
    strip = template.index("УБЕРИ")
    forbid = template.index("Не добавляй ссылок")
    assert keep < strip < forbid, "порядок правил: сохранить → убрать → не добавлять"
    assert forbid - keep < 600, "правила разъехались по промпту"


@pytest.mark.parametrize("style", ["default", "news", "opinion", "instruction", "humor"])
def test_link_block_says_it_has_no_other_exceptions(style):
    """Без явного «других исключений нет» модель охотно придумывает свои —
    например, оставляет ссылку на первоисточник «для честности»."""
    assert "других исключений нет" in resolve_rewrite_template(style)


def test_github_link_survives_article_url_filter():
    """Смежная проверка: ссылка на репозиторий не должна отсеиваться как
    «за этим хостом статьи нет» — README вполне читается и обогащает рерайт."""
    from tg_repost.enrichment.link_content import extract_article_urls

    post = "Новый инструмент: https://github.com/user/repo\nПодпишись https://t.me/ch"
    assert extract_article_urls(post) == ["https://github.com/user/repo"]


def test_humanize_block_lists_concrete_ai_tells_not_vague_advice():
    """«Пиши живее» модель игнорирует. Работают конкретные запрещённые
    обороты, по которым текст и опознаётся как машинный."""
    block = get_settings().rewrite_humanize_instructions
    for marker in ("не просто", "стоит отметить", "таким образом", "подводя итог"):
        assert marker in block


def test_humanize_block_never_wraps_a_quoted_phrase_across_lines():
    """Запрещённый оборот, разорванный переносом строки («таким\\n образом»),
    перестаёт читаться как цельная фраза — и правило слабеет ровно там, где
    оно должно быть буквальным. Найдено тестом на реальном тексте."""
    import re

    block = get_settings().rewrite_humanize_instructions
    broken = [m for m in re.findall(r"«[^»]*»", block) if "\n" in m]
    assert broken == [], f"обороты разорваны переносом: {broken}"
