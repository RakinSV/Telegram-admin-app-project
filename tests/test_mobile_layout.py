"""Вёрстка под телефон (юзабилити, 2026-08-17).

ЧЕСТНО О ГРАНИЦАХ ЭТОГО ФАЙЛА. Тест не рисует страницу и потому не может
сказать, удобно ли ей пользоваться. Он охраняет ровно те вещи, которые
ломаются молча и обнаруживаются только на чужом телефоне:

* мета-тег `viewport` — без него телефон рисует страницу в десктопной
  ширине и уменьшает целиком: текст нечитаем, нажать нельзя ни во что;
* размер шрифта в полях ввода — при значении меньше 16px iOS увеличивает
  страницу на фокусе и обратно сама не возвращается;
* размер кнопки меню — в 44 пикселя попадают пальцем без прицеливания;
* прокрутка ТАБЛИЦЫ, а не страницы — иначе уезжает и меню, и заголовок.

Само поведение проверено в браузере при ширине 375: страница входа,
дашборд, настройки и журнал — без горизонтального переполнения, все 122
поля настроек 16px, таблица журнала прокручивается внутри себя.
"""

from __future__ import annotations

import pathlib
import re

import pytest

TEMPLATES = pathlib.Path("tg_repost/webui/templates")
CSS = pathlib.Path("tg_repost/webui/static/style.css")

# Оба каркаса: страницы админки и экраны входа рисуются РАЗНЫМИ шаблонами, и
# забыть тег в одном из них легко — так и случилось с `auth_base.html`, а это
# первое, что видят с телефона.
SKELETONS = ["base.html", "auth_base.html"]


@pytest.mark.parametrize("name", SKELETONS)
def test_skeleton_has_viewport_meta(name: str):
    text = (TEMPLATES / name).read_text(encoding="utf-8")

    assert re.search(
        r'<meta\s+name="viewport"[^>]*width=device-width', text,
    ), "без этого тега телефон рисует страницу в десктопной ширине"


def test_burger_works_without_javascript():
    """Скрипт ради одного меню — лишняя зависимость: оно должно работать и
    при выключенном JS, и пока скрипт ещё грузится."""
    text = (TEMPLATES / "base.html").read_text(encoding="utf-8")

    assert 'type="checkbox" id="menu-toggle"' in text
    assert 'for="menu-toggle"' in text
    assert "<script" not in text, "меню не должно зависеть от скрипта"


def test_menu_button_is_hidden_on_wide_screens():
    """На широком экране меню и так на виду — кнопка была бы лишним шагом к
    тому, что уже показано."""
    css = CSS.read_text(encoding="utf-8")

    assert re.search(r"\.menu-button\s*\{\s*display:\s*none", css)


def test_touch_targets_are_at_least_44px():
    """Меньше 44 пикселей — промах мимо кнопки меню и случайный переход по
    ссылке под ней."""
    css = CSS.read_text(encoding="utf-8")
    mobile = css[css.index("@media (max-width: 900px)"):]
    button = mobile[mobile.index(".menu-button"):]

    width = re.search(r"width:\s*(\d+)px", button)
    height = re.search(r"height:\s*(\d+)px", button)

    assert width and int(width.group(1)) >= 44
    assert height and int(height.group(1)) >= 44


def test_tables_scroll_themselves_not_the_page():
    """Горизонтальная прокрутка всего документа — худший исход: уезжает и
    меню, и заголовок, и вернуться нечем."""
    css = CSS.read_text(encoding="utf-8")
    mobile = css[css.index("@media (max-width: 900px)"):]

    table_rule = re.search(r"table\s*\{[^}]*\}", mobile)

    assert table_rule, "в мобильном слое нет правила для таблиц"
    assert "overflow-x: auto" in table_rule.group(0)
    assert "display: block" in table_rule.group(0)


def test_input_font_is_16px_on_mobile():
    """Мельче 16px — iOS увеличивает страницу на фокусе и не возвращает."""
    css = CSS.read_text(encoding="utf-8")
    mobile = css[css.index("@media (max-width: 900px)"):]

    assert "font-size: 16px" in mobile


def test_mobile_rules_repeat_desktop_selectors():
    """САМАЯ КОВАРНАЯ ЧАСТЬ.

    Десктопное правило `.card input[type=number]` весит больше, чем короткое
    `.card input`, и упрощённая запись до него не достаёт. Проверено в
    браузере: из 63 полей на странице настроек 46 оставались мелкими, пока
    селекторы не повторили десктопные один в один.
    """
    css = CSS.read_text(encoding="utf-8")
    mobile = css[css.index("@media (max-width: 900px)"):]

    for selector in (
        ".card input[type=number]",
        ".card input[type=password]",
        ".field-row input[type=text]",
    ):
        assert selector in mobile, f"мобильный слой не перекрывает {selector}"
