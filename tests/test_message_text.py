"""Скрытые ссылки Telegram: URL живёт в entities, а не в тексте.

Жалоба «ссылки на гитхаб не сохраняются» оказалась не про промпт: в постах
таких ссылок не было ВООБЩЕ — `message.message` отдаёт только видимые
символы, и URL под словом-якорем терялся ещё до рерайта.
"""

from __future__ import annotations

from types import SimpleNamespace

from tg_repost.telegram.message_text import expand_hidden_links


def _entity(offset: int, length: int, url: str | None = None):
    return SimpleNamespace(offset=offset, length=length, url=url)


def test_hidden_link_becomes_visible_url():
    text = "Смотри Github там всё"
    entities = [_entity(7, 6, "https://github.com/foo/bar")]
    assert expand_hidden_links(text, entities) == (
        "Смотри Github (https://github.com/foo/bar) там всё"
    )


def test_expanded_url_is_picked_up_by_the_article_extractor():
    """Смысл раскрытия: ссылка должна дойти и до промпта, и до перехода по
    ней — иначе правило «ссылку на репозиторий сохрани» нечему применять."""
    from tg_repost.enrichment.link_content import extract_article_urls

    text = expand_hidden_links("Исходники тут", [_entity(0, 9, "https://github.com/o/r")])
    assert extract_article_urls(text) == ["https://github.com/o/r"]


def test_entities_without_url_are_left_alone():
    """Жирный шрифт, код, упоминания — тоже entity, но раскрывать нечего."""
    text = "Обычный жирный текст"
    assert expand_hidden_links(text, [_entity(8, 6)]) == text


def test_visible_url_is_not_duplicated():
    text = "Ссылка https://github.com/o/r вот"
    entities = [_entity(7, 22, "https://github.com/o/r")]
    assert expand_hidden_links(text, entities) == text


def test_offsets_are_measured_in_utf16_like_telegram_does():
    """Эмодзи вне BMP занимает ДВЕ единицы: если считать питоновскими
    символами, якорь съедет и ссылка воткнётся в середину слова."""
    text = "🔥 Github тут"          # 🔥 = 2 единицы, пробел = 1 → якорь с 3
    entities = [_entity(3, 6, "https://github.com/o/r")]
    assert expand_hidden_links(text, entities) == "🔥 Github (https://github.com/o/r) тут"


def test_several_hidden_links_all_expand():
    text = "первая и вторая"
    entities = [
        _entity(0, 6, "https://github.com/a/one"),
        _entity(9, 6, "https://gitlab.com/b/two"),
    ]
    result = expand_hidden_links(text, entities)
    assert "первая (https://github.com/a/one)" in result
    assert "вторая (https://gitlab.com/b/two)" in result


def test_broken_offsets_do_not_raise():
    """Текст важнее раскрытия: битые смещения пропускаем молча."""
    assert expand_hidden_links("коротко", [_entity(50, 10, "https://x.dev")]) == "коротко"


def test_no_entities_returns_text_unchanged():
    assert expand_hidden_links("просто текст", None) == "просто текст"
    assert expand_hidden_links("", [_entity(0, 1, "https://x.dev")]) == ""
