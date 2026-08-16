"""Боковое меню (аудит юзабилити 2026-08-16).

Меню росло по пункту на фичу и доросло до 34 ссылок плоским списком —
примерно 1200 пикселей высоты без единого заголовка. Владелец сформулировал
результат прямо: «зашёл в админку, ничего не понятно».

Здесь проверяется не вёрстка, а два свойства, которые легко потерять при
следующей фиче: ни одна страница не выпала из меню, и группа, из которой
роли ничего не доступно, не рисует пустой заголовок.
"""

from __future__ import annotations

import pytest

from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401
from tg_repost.db.models import AdminUser
from tg_repost.db.session import session_scope
from tg_repost.webui import access, i18n, nav
from tg_repost.webui.auth import hash_password


def test_every_group_title_is_translated():
    for group in nav.NAV:
        if group.title_key is None:
            continue
        assert group.title_key in i18n.STRINGS, group.title_key


def test_every_item_label_is_translated():
    for group in nav.NAV:
        for item in group.items:
            assert item.label_key in i18n.STRINGS, item.label_key


def test_no_duplicate_links():
    hrefs = nav.all_hrefs()

    assert len(hrefs) == len(set(hrefs)), "пункт продублирован"


def test_every_link_leads_somewhere():
    """Пункт меню в никуда — это 404 вместо страницы."""
    from tg_repost.webui.app import create_app

    paths = set(create_app().openapi()["paths"])

    missing = [h for h in nav.all_hrefs() if h not in paths]
    assert not missing, f"пункты ведут на несуществующие адреса: {missing}"


def test_every_admin_page_is_in_the_menu():
    """СТРАНИЦА БЕЗ ПУНКТА МЕНЮ — ЭТО СТРАНИЦА, КОТОРУЮ НЕ НАЙТИ.

    Ровно так и терялись фичи: код есть, дойти нельзя. Исключения —
    страницы, на которые заходят по ссылке из другой страницы или снаружи.
    """
    from tg_repost.webui.app import create_app

    # Открываются из других экранов или не являются страницами админки.
    NOT_IN_MENU = {
        "/login", "/logout", "/setup", "/health", "/openapi.json",
        "/app", "/app/data",                  # мини-апп для участников
        "/growth", "/stats/best-times", "/stats/growth",  # вкладки статистики
        # Постоянный редирект на /settings для старых закладок: секреты и
        # настройки давно на одной странице.
        "/secrets",
        # Открывается со страницы воронок кнопкой «новая».
        "/funnels/new",
    }

    pages = {
        p for p, ops in create_app().openapi()["paths"].items()
        if "get" in ops and "{" not in p and not p.startswith("/api/")
        and not p.startswith("/setup") and not p.startswith("/lang")
        and not p.startswith("/components/") and not p.startswith("/export/")
        and not p.startswith("/logs/")
    }
    in_menu = set(nav.all_hrefs())

    orphans = sorted(pages - in_menu - NOT_IN_MENU)
    assert not orphans, f"страницы без пункта меню: {orphans}"


# --- поведение при разных ролях ---


def _login_as(client, role: str) -> None:
    username = f"user_{role}"
    with session_scope() as session:
        session.add(AdminUser(
            username=username, role=role,
            password_hash=hash_password("another-strong-pass"),
        ))
    client.post(
        "/login", data={"username": username, "password": "another-strong-pass"},
        follow_redirects=False,
    )


def test_owner_sees_every_group():
    client = _client()
    _bootstrap(client)

    body = client.get("/").text

    for group in nav.NAV:
        if group.title_key:
            assert i18n.STRINGS[group.title_key]["ru"] in body, group.title_key


def test_group_with_nothing_available_is_hidden_entirely(monkeypatch):
    """Заголовок без единой доступной ссылки заставляет искать то, чего нет.

    Проверяется на СИНТЕТИЧЕСКОЙ группе из одних владельческих страниц: в
    боевом составе такой сейчас нет — в «Деньгах» аналитику доступен
    медиакит, в «Системе» логи. Проверять защиту на данных, где она не
    срабатывает, значило бы не проверять ничего.
    """
    owner_only = nav.NavGroup("nav.group.system", (
        nav.NavItem("/settings", "nav.settings"),
        nav.NavItem("/users", "nav.users"),
    ))
    monkeypatch.setattr(nav, "NAV", (owner_only,))

    client = _client()
    _bootstrap(client)
    _login_as(client, access.ROLE_ANALYST)

    body = client.get("/stats").text

    assert i18n.STRINGS["nav.group.system"]["ru"] not in body


def test_the_same_group_is_shown_to_the_owner(monkeypatch):
    """Проверка самой проверки: та же группа владельцу видна.

    Без неё тест выше проходил бы и на коде, который не рисует меню вовсе.
    """
    owner_only = nav.NavGroup("nav.group.system", (
        nav.NavItem("/settings", "nav.settings"),
    ))
    monkeypatch.setattr(nav, "NAV", (owner_only,))

    client = _client()
    _bootstrap(client)

    body = client.get("/").text

    assert i18n.STRINGS["nav.group.system"]["ru"] in body


def test_analyst_sees_money_group_only_because_of_mediakit():
    """Фильтрация внутри группы работает: доступный пункт остаётся, чужие
    уходят."""
    client = _client()
    _bootstrap(client)
    _login_as(client, access.ROLE_ANALYST)

    body = client.get("/stats").text

    assert 'href="/mediakit"' in body
    assert 'href="/shop"' not in body
    assert 'href="/crypto"' not in body


def test_analyst_still_sees_what_they_can_open():
    client = _client()
    _bootstrap(client)
    _login_as(client, access.ROLE_ANALYST)

    body = client.get("/stats").text

    assert 'href="/stats"' in body
    assert 'href="/mediakit"' in body


def test_editor_sees_content_and_audience():
    client = _client()
    _bootstrap(client)
    _login_as(client, access.ROLE_EDITOR)

    body = client.get("/moderation").text

    assert i18n.STRINGS["nav.group.content"]["ru"] in body
    assert i18n.STRINGS["nav.group.audience"]["ru"] in body
    assert 'href="/settings"' not in body


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_menu_has_no_missing_translations(lang):
    import re

    client = _client()
    _bootstrap(client)
    client.get(f"/lang/{lang}?next=/", follow_redirects=False)

    body = client.get("/").text

    assert not re.compile(r"\[nav\.[a-z_.]+\]").findall(body)
