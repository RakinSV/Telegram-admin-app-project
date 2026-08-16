"""Единообразие страниц админки (аудит юзабилити 2026-08-16).

Страницы писались по одной, на протяжении месяцев, и ни разу не
просматривались подряд. Разнобой в таких условиях появляется не от небрежности,
а от того, что каждую новую страницу сравнивают с последней, а не со всеми.

Проверяется то, что можно измерить и что реально мешает человеку:

* **заголовок** — без него непонятно, куда попал;
* **пояснение под заголовком** — «что это за экран и зачем»; именно его
  отсутствие владелец назвал «ничего не понятно»;
* **пустое состояние у таблицы** — иначе видно шапку и пустоту, и непонятно,
  сломалось или данных нет;
* **текст мимо переводов** — в английском интерфейсе он остаётся русским.

ИСКЛЮЧЕНИЯ НАЗВАНЫ ПОИМЁННО И С ПРИЧИНОЙ. Список исключений без объяснения
через полгода превращается в «так исторически сложилось», и правило умирает.
"""

from __future__ import annotations

import pathlib
import re

import pytest

TEMPLATES = pathlib.Path("tg_repost/webui/templates")

# Не самостоятельные страницы админки.
NOT_A_PAGE = {
    "base.html",          # каркас
    "auth_base.html",     # каркас экранов входа
    "_macros.html",       # макросы
    "components.html",    # фрагмент, встраивается в другие
    "miniapp.html",       # мини-апп: своя оболочка со своими правилами
    "miniapp_data.html",  # фрагмент мини-аппа
    "miniapp_denied.html",
}

# Экраны, где пояснение под заголовком не нужно, — с причиной.
NO_INTRO_NEEDED = {
    # Форма входа: объяснять, что такое «Вход», незачем.
    "login.html",
    "telethon_login.html",
    # Настройки: у каждой ГРУППЫ полей своё описание, общее поверх них было
    # бы третьим уровнем текста подряд.
    "settings.html",
    "guardian_settings.html",
    # Страницы, открытые из списка: контекст человек принёс с собой, а
    # предпросмотр рассылки и правка воронки объясняют себя предупреждениями
    # по месту.
    "broadcast_preview.html",
    "funnel_edit.html",
    "source_detail.html",
    "support_thread.html",
    "affiliate_detail.html",
    "contact_detail.html",
    "moderation_detail.html",
}


# Циклы, которые пустыми не бывают, — по КОНКРЕТНОМУ циклу, а не по файлу
# целиком: исключение на весь файл сняло бы проверку и с соседних таблиц.
NO_EMPTY_STATE_NEEDED = {
    # Владелец создаётся при установке и удалить себя не может, поэтому
    # список администраторов никогда не пуст. Пустое состояние здесь было бы
    # разметкой, до которой нельзя дойти, — ровно тем, что в этом проекте
    # считается недоделанным кодом.
    ("users.html", "user in users"),
    # Сетка календаря — это диапазон дней, он всегда непустой по построению.
    ("calendar.html", "cell in view.days"),
}


def _pages() -> list[pathlib.Path]:
    return sorted(p for p in TEMPLATES.glob("*.html") if p.name not in NOT_A_PAGE)


_TAG = re.compile(r"\{%-?\s*(for|if|endfor|endif|else)\b")


def _for_has_else(block: str) -> bool:
    """Есть ли у цикла СВОЙ `{% else %}`, а не чужой изнутри условия.

    Простая проверка «есть ли `{% else %}` в таблице» оказалась беззубой:
    её удовлетворял любой `{% if %}...{% else %}` внутри ячейки, и таблица
    без пустого состояния проходила проверку. Поймано диверсией — удалением
    настоящего пустого состояния, после которого тест продолжал зеленеть.

    Поэтому считаем глубину: `else` принадлежит циклу, только если встретился
    на его собственном уровне вложенности.
    """
    depth = 0
    in_for = False
    for match in _TAG.finditer(block):
        tag = match.group(1)
        if tag == "for":
            if not in_for:
                in_for, depth = True, 0
            else:
                depth += 1
        elif tag == "if":
            depth += 1
        elif tag in ("endif",):
            depth -= 1
        elif tag == "endfor":
            if in_for and depth == 0:
                in_for = False
            else:
                depth -= 1
        elif tag == "else" and in_for and depth == 0:
            return True
    return False


def _strip_comments(text: str) -> str:
    without_jinja = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
    without_css = re.sub(r"/\*.*?\*/", "", without_jinja, flags=re.S)
    return re.sub(r"<!--.*?-->", "", without_css, flags=re.S)


@pytest.mark.parametrize("path", _pages(), ids=lambda p: p.name)
def test_page_has_a_heading(path: pathlib.Path):
    """Страница без заголовка — «куда я попал?»."""
    text = path.read_text(encoding="utf-8")

    assert re.search(r"<h1[ >]", text), "нет заголовка h1"


@pytest.mark.parametrize("path", _pages(), ids=lambda p: p.name)
def test_page_explains_itself(path: pathlib.Path):
    """Пояснение сразу под заголовком: что это за экран и зачем.

    Именно его отсутствие и складывается в «зашёл — ничего не понятно».
    """
    if path.name in NO_INTRO_NEEDED:
        pytest.skip("объясняет себя иначе — см. NO_INTRO_NEEDED")

    text = path.read_text(encoding="utf-8")

    assert re.search(r"<h1[^>]*>.*?</h1>\s*\n\s*<p class=\"muted\">", text, re.S), (
        "под заголовком нет пояснения «что это за экран»"
    )


@pytest.mark.parametrize("path", _pages(), ids=lambda p: p.name)
def test_tables_say_when_they_are_empty(path: pathlib.Path):
    """Шапка таблицы и пустота под ней не отличимы от поломки.

    Таблица, спрятанная целиком под `{% if %}`, — тот же приём другими
    средствами и потому допустима.
    """
    text = path.read_text(encoding="utf-8")

    for match in re.finditer(r"<table>.*?</table>", text, re.S):
        block = match.group(0)
        if "{% for" not in block or _for_has_else(block):
            continue

        header = re.search(r"\{%-?\s*for\s+(.+?)\s*-?%\}", block)
        loop = header.group(1) if header else ""
        if (path.name, loop) in NO_EMPTY_STATE_NEEDED:
            continue
        # Блок под условием: пустого состояния не требуется, его роль
        # выполняет само условие. Определяется БАЛАНСОМ незакрытых `{% if %}`
        # до таблицы, а не соседними строками: между условием и таблицей
        # обычно стоят карточка, заголовок и пояснение.
        before = text[: match.start()]
        opened = len(re.findall(r"\{%-?\s*if\b", before))
        closed = len(re.findall(r"\{%-?\s*endif\b", before))
        assert opened > closed, (
            f"таблица без пустого состояния и без условия вокруг "
            f"(строка {before.count(chr(10)) + 1})"
        )


@pytest.mark.parametrize("path", _pages(), ids=lambda p: p.name)
def test_no_russian_text_outside_translations(path: pathlib.Path):
    """Текст в разметке остаётся русским при английском интерфейсе."""
    text = _strip_comments(path.read_text(encoding="utf-8"))

    offenders = [
        line.strip()
        for line in text.splitlines()
        if re.search(r"[А-Яа-яЁё]", line) and "t(" not in line
    ]

    assert not offenders, f"текст мимо переводов: {offenders[:3]}"
