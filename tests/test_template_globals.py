"""Общие глобальные значения шаблонов (аудит 2026-08-16).

`base.html` — один на всю админку, но `Jinja2Templates` создаётся в КАЖДОМ
модуле роутов со своим окружением. Значит любое значение, зарегистрированное
только в одном модуле, отсутствует на страницах всех остальных — а заметно
это лишь на конкретной странице и только глазами.

Тест проходит по страницам из РАЗНЫХ модулей роутов и требует, чтобы общие
элементы `base.html` были на каждой.
"""

from __future__ import annotations

import pytest

from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401

# По одной странице на модуль роутов — именно в этом смысл списка.
PAGES = [
    "/",              # app.py
    "/ads",           # crud_routes.py
    "/support",       # support_routes.py
    "/funnels",       # funnels_routes.py
    "/contacts",      # contacts_routes.py
    "/broadcasts",    # broadcasts_routes.py
    "/mediakit",      # mediakit_routes.py
    "/calendar",      # calendar_routes.py
    "/ad-requests",   # ad_requests_routes.py
    "/invites",       # invites_routes.py
    "/users",         # users_routes.py
    "/guardian",      # guardian_routes.py
]


@pytest.fixture
def _client_logged():
    # Именно функциональная область видимости: изолирующая окружение
    # фикстура тоже функциональная, а на модульной клиент собирался бы
    # раньше неё и лез в настоящие настройки Telethon.
    client = _client()
    _bootstrap(client)
    return client


@pytest.mark.parametrize("path", PAGES)
def test_language_switcher_is_on_every_page(_client_logged, path):
    """Переключатель языка живёт в `base.html` и обязан быть везде.

    Он строится по `SUPPORTED_LANGS`, а тот регистрировался только в
    окружении `app.py`. На страницах из других модулей список оказывался
    неопределённым, и переключатель просто исчезал — при этом страница
    отдавала 200, поэтому ни один тест этого не видел.
    """
    response = _client_logged.get(path)

    assert response.status_code == 200, path
    assert "/lang/ru" in response.text, f"нет переключателя языка: {path}"
    assert "/lang/en" in response.text, f"нет переключателя языка: {path}"


@pytest.mark.parametrize("path", PAGES)
def test_navigation_is_on_every_page(_client_logged, path):
    """Меню тоже общее: страница без него — тупик, из которого не выйти."""
    response = _client_logged.get(path)

    assert 'href="/moderation"' in response.text, f"нет меню: {path}"
