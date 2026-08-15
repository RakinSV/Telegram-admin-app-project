"""UTM-метки на исходящих ссылках (F59).

Пост уходит подписчикам ОДИН РАЗ. Битая ссылка в нём — это не «поправим и
перевыложим», а потерянные переходы и вопрос «что у вас с ссылками».
Поэтому почти все тесты здесь про то, что текст НЕ испорчен.
"""

from __future__ import annotations

from tg_repost import utm

PARAMS = {
    "utm_source": "telegram",
    "utm_medium": "channel",
    "utm_campaign": "post_42",
}


# --- базовая разметка ---


def test_adds_params_to_plain_url():
    result = utm.add_utm("https://example.com/article", PARAMS)

    assert "utm_source=telegram" in result
    assert "utm_medium=channel" in result
    assert result.startswith("https://example.com/article?")


def test_existing_query_is_preserved():
    """Ссылка с параметрами должна остаться рабочей."""
    result = utm.add_utm("https://example.com/a?ref=abc&id=7", PARAMS)

    assert "ref=abc" in result
    assert "id=7" in result
    assert "utm_source=telegram" in result


def test_fragment_is_preserved():
    """Якорь после меток, а не потерян: иначе ссылка ведёт не туда."""
    result = utm.add_utm("https://example.com/doc#section-3", PARAMS)

    assert result.endswith("#section-3")
    assert "utm_source=telegram" in result


def test_already_tagged_link_is_untouched():
    """Повторная публикация (F55) не должна удваивать метки."""
    url = "https://example.com/a?utm_source=newsletter"

    assert utm.add_utm(url, PARAMS) == url


def test_empty_params_change_nothing():
    url = "https://example.com/a"

    assert utm.add_utm(url, {}) == url


def test_blank_values_are_dropped():
    result = utm.add_utm(
        "https://example.com/a",
        {"utm_source": "telegram", "utm_medium": "", "utm_campaign": "x"},
    )

    assert "utm_medium" not in result
    assert "utm_source=telegram" in result


# --- что НЕ размечаем ---


def test_telegram_links_are_never_tagged():
    """Метки там бессмысленны, а инвайт-ссылку лишний параметр может сломать."""
    for url in (
        "https://t.me/mychannel",
        "https://t.me/+AbCdEf123",
        "https://telegram.me/somebot",
        "https://telegra.ph/article-01-01",
    ):
        assert utm.add_utm(url, PARAMS) == url, url


def test_subdomain_of_skipped_host_also_skipped():
    assert utm.add_utm("https://api.telegram.org/x", PARAMS) == (
        "https://api.telegram.org/x"
    )


def test_lookalike_domain_is_not_skipped():
    """`nott.me` — не `t.me`.

    Проверка по окончанию строки без границы пропустила бы чужой домен.
    """
    result = utm.add_utm("https://nott.me/page", PARAMS)

    assert "utm_source=telegram" in result


# --- текст поста ---


def test_tags_every_link_in_text():
    text = "Читайте https://example.com/a и https://other.org/b"

    result = utm.tag_links(text, PARAMS)

    assert result.count("utm_source=telegram") == 2


def test_trailing_punctuation_stays_outside_the_link():
    """«Читайте на example.com/пост.» — точка это конец предложения.

    Втянув её в ссылку, мы получим 404 у каждого, кто по ней перейдёт.
    """
    result = utm.tag_links("Подробнее: https://example.com/post.", PARAMS)

    assert result.endswith(".")
    assert "post?utm_source" in result


def test_various_trailing_marks():
    for mark in (",", ";", "!", "?", "»", ":"):
        result = utm.tag_links(f"тут https://example.com/x{mark} дальше", PARAMS)
        assert f"{mark} дальше" in result, mark


def test_text_without_links_is_unchanged():
    text = "Обычный пост без ссылок вообще"

    assert utm.tag_links(text, PARAMS) == text


def test_telegram_mention_is_not_a_link():
    """@упоминания и t.me-текст трогать нечего."""
    text = "Пишите @support или в https://t.me/support"

    result = utm.tag_links(text, PARAMS)

    assert result == text


def test_mixed_text_keeps_telegram_and_tags_external():
    text = "Наш канал https://t.me/mychannel, а магазин https://shop.example/x"

    result = utm.tag_links(text, PARAMS)

    assert "https://t.me/mychannel," in result
    assert "utm_source=telegram" in result
    assert result.count("utm_source") == 1


def test_empty_text_is_safe():
    assert utm.tag_links("", PARAMS) == ""


def test_no_params_leaves_text_alone():
    text = "ссылка https://example.com/a"

    assert utm.tag_links(text, {}) == text


# --- сборка меток ---


def test_post_id_is_substituted():
    params = utm.build_params(
        source="telegram", medium="channel",
        campaign_template="post_{post_id}", post_id=99,
    )

    assert params["utm_campaign"] == "post_99"


def test_template_without_placeholder_is_used_as_is():
    params = utm.build_params(
        source="tg", medium="social", campaign_template="autumn_sale", post_id=1,
    )

    assert params["utm_campaign"] == "autumn_sale"


def test_missing_post_id_does_not_leave_placeholder():
    """`post_{post_id}` без id превратился бы в мусор в отчёте аналитики."""
    params = utm.build_params(
        source="tg", medium="social", campaign_template="post_{post_id}",
    )

    assert "{post_id}" not in params["utm_campaign"]
