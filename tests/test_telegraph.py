"""Тесты публикации лонгридов на Telegraph: конвертер разметки, тизер,
кодирование контента. Без сети — HTTP подменяется, конвертер чистый.
"""

from __future__ import annotations

import json

import pytest

from tg_repost.telegraph.article import build_teaser
from tg_repost.telegraph.client import TelegraphError, _encode_content
from tg_repost.telegraph.nodes import (
    extract_title,
    image_node,
    markdown_to_nodes,
)

# --- заголовок ---


def test_extract_title_from_heading():
    title, body = extract_title("# Заголовок\n\nПервый абзац.")
    assert title == "Заголовок"
    assert body == "Первый абзац."


def test_extract_title_falls_back_to_first_line():
    """Модель может забыть «#» — статья важнее формата ответа."""
    title, body = extract_title("Просто первая строка\n\nтело")
    assert title == "Просто первая строка"
    assert body == "тело"


def test_extract_title_skips_leading_blank_lines():
    title, _ = extract_title("\n\n\n# Заголовок\n\nтекст")
    assert title == "Заголовок"


def test_extract_title_empty_input():
    assert extract_title("") == ("", "")


def test_title_not_duplicated_in_body():
    """Telegraph принимает title отдельным полем: оставшись и в контенте,
    заголовок продублировался бы на странице."""
    _, body = extract_title("# Заголовок\n\nтекст")
    assert "Заголовок" not in body


# --- блочная разметка ---


def test_code_block_keeps_newlines_and_is_not_inline_parsed():
    """Внутри ``` не должно работать ни форматирование, ни склейка строк:
    иначе отступы схлопнутся, а * и _ в коде станут тегами."""
    nodes = markdown_to_nodes("```python\nif a and b:\n    x = a * b\n```")
    assert nodes == [{
        "tag": "pre",
        "children": [{"tag": "code", "children": ["if a and b:\n    x = a * b"]}],
    }]


def test_unclosed_code_fence_still_yields_code():
    nodes = markdown_to_nodes("```\nprint(1)")
    assert nodes[0]["tag"] == "pre"
    assert "print(1)" in nodes[0]["children"][0]["children"][0]


def test_headings_map_to_h3_and_h4_only():
    """У Telegraph НЕТ h1/h2 — только h3 и h4."""
    nodes = markdown_to_nodes("# A\n\n## B\n\n### C\n\n#### D")
    assert [n["tag"] for n in nodes] == ["h3", "h3", "h4", "h4"]


def test_paragraph_lines_are_joined():
    nodes = markdown_to_nodes("первая строка\nвторая строка\n\nновый абзац")
    assert len(nodes) == 2
    assert nodes[0]["children"] == ["первая строка вторая строка"]


def test_bullet_and_numbered_lists():
    nodes = markdown_to_nodes("- один\n- два\n\n1. первый\n2. второй")
    assert nodes[0]["tag"] == "ul"
    assert len(nodes[0]["children"]) == 2
    assert nodes[1]["tag"] == "ol"
    assert nodes[1]["children"][0]["children"] == ["первый"]


def test_blockquote_and_hr():
    nodes = markdown_to_nodes("> цитата\n\n---")
    assert nodes[0]["tag"] == "blockquote"
    assert nodes[1] == {"tag": "hr"}


def test_list_directly_after_paragraph_is_not_swallowed():
    nodes = markdown_to_nodes("Что умеет:\n- следить\n- фильтровать")
    assert [n["tag"] for n in nodes] == ["p", "ul"]


# --- инлайн-разметка ---


def test_inline_bold_italic_code():
    nodes = markdown_to_nodes("тут **жирный**, *курсив* и `код`")
    tags = [c["tag"] for c in nodes[0]["children"] if isinstance(c, dict)]
    assert tags == ["strong", "em", "code"]


def test_inline_code_is_parsed_before_emphasis():
    """Звёздочки ВНУТРИ инлайн-кода не должны стать курсивом."""
    nodes = markdown_to_nodes("значение `a * b` тут")
    children = nodes[0]["children"]
    code = next(c for c in children if isinstance(c, dict))
    assert code == {"tag": "code", "children": ["a * b"]}


def test_bare_url_becomes_link():
    nodes = markdown_to_nodes("репозиторий https://github.com/user/repo вот")
    link = next(c for c in nodes[0]["children"] if isinstance(c, dict))
    assert link["tag"] == "a"
    assert link["attrs"]["href"] == "https://github.com/user/repo"


def test_url_trailing_punctuation_stays_as_text():
    """«(см. https://example.com/a)» не должно съесть закрывающую скобку."""
    nodes = markdown_to_nodes("(см. https://example.com/a)")
    link = next(c for c in nodes[0]["children"] if isinstance(c, dict))
    assert link["attrs"]["href"] == "https://example.com/a"
    assert nodes[0]["children"][-1] == ")"


def test_markdown_link():
    nodes = markdown_to_nodes("[документация](https://example.com/docs)")
    link = nodes[0]["children"][0]
    assert link["attrs"]["href"] == "https://example.com/docs"
    assert link["children"] == ["документация"]


def test_angle_brackets_stay_plain_text():
    """Главное преимущество перед parse_mode: экранировать нечего, «<» в
    тексте остаётся текстом и инъекцией стать не может."""
    nodes = markdown_to_nodes("если a < b и c & d")
    assert nodes[0]["children"] == ["если a < b и c & d"]


# --- картинки ---


def test_image_node_with_and_without_caption():
    assert image_node("https://e.com/x.png") == {
        "tag": "figure", "children": [{"tag": "img", "attrs": {"src": "https://e.com/x.png"}}],
    }
    with_cap = image_node("https://e.com/x.png", "подпись")
    assert with_cap["children"][1] == {"tag": "figcaption", "children": ["подпись"]}


# --- лимит страницы ---


def test_encode_content_rejects_oversized_page():
    huge = [{"tag": "p", "children": ["я" * 40_000]}]
    with pytest.raises(TelegraphError, match="лимит"):
        _encode_content(huge)


def test_encode_content_is_valid_json_without_ascii_escaping():
    encoded = _encode_content([{"tag": "p", "children": ["Привет"]}])
    assert "Привет" in encoded  # не \u-escape, иначе лимит 64 КБ тратится втрое
    assert json.loads(encoded)[0]["children"] == ["Привет"]


# --- тизер ---


def test_teaser_contains_title_first_paragraph_and_link():
    teaser = build_teaser("Заголовок", "Первый абзац.\n\nВторой.", "https://telegra.ph/x", 900)
    assert teaser.startswith("Заголовок")
    assert "Первый абзац." in teaser
    assert teaser.endswith("https://telegra.ph/x")
    assert "Второй." not in teaser


def test_teaser_skips_headings_and_code_when_picking_first_paragraph():
    body = "## Раздел\n\n```\ncode\n```\n\nНастоящий вводный абзац."
    teaser = build_teaser("T", body, "https://telegra.ph/x", 900)
    assert "Настоящий вводный абзац." in teaser
    assert "code" not in teaser


def test_teaser_respects_limit_and_never_cuts_the_link():
    url = "https://telegra.ph/very-long-article-slug"
    teaser = build_teaser("Заголовок", "я" * 5000, url, 300)
    assert len(teaser) <= 300
    assert teaser.endswith(url)  # ссылка обязана уцелеть — без неё тизер пуст


def test_teaser_without_body_is_just_title_and_link():
    teaser = build_teaser("Только заголовок", "", "https://telegra.ph/x", 900)
    assert teaser == "Только заголовок\n\nhttps://telegra.ph/x"


# --- сквозной прогон разметки ---


def test_full_article_roundtrip_produces_expected_tag_sequence():
    article = (
        "# Новый инструмент\n\n"
        "Вышел **logtool**. Репозиторий: https://github.com/user/logtool\n\n"
        "## Установка\n\n"
        "```bash\npip install logtool\n```\n\n"
        "- следит за файлом\n- фильтрует\n\n"
        "> Только Linux.\n"
    )
    title, body = extract_title(article)
    nodes = markdown_to_nodes(body)
    assert title == "Новый инструмент"
    assert [n["tag"] for n in nodes] == ["p", "h3", "pre", "ul", "blockquote"]
    _encode_content(nodes)  # не должно бросить: статья в лимит помещается
