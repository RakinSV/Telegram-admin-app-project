"""Роли и доступ к страницам админки (F37).

Две вещи здесь важнее всего, и обе — про то, как система ведёт себя при
ошибке разработчика, а не при правильном использовании:

1. **Запрет по умолчанию.** Страница, забытая в политике доступа, должна
   быть закрыта для всех, кроме владельца. Обратный порядок однажды тихо
   откроет сотруднику страницу секретов.
2. **Нельзя остаться без владельца.** Система без владельца — это система,
   куда некому войти за настройками, и выбраться из этого через интерфейс
   невозможно: страницу пользователей тоже открывает только владелец.
"""

from __future__ import annotations

import pytest

from tg_repost.webui import access


# --- уровни ролей ---


def test_owner_can_do_everything():
    for needed in access.ALL_ROLES:
        assert access.can(access.ROLE_OWNER, needed) is True


def test_editor_cannot_reach_owner_pages():
    assert access.can(access.ROLE_EDITOR, access.ROLE_EDITOR) is True
    assert access.can(access.ROLE_EDITOR, access.ROLE_ANALYST) is True
    assert access.can(access.ROLE_EDITOR, access.ROLE_OWNER) is False


def test_analyst_can_only_read():
    assert access.can(access.ROLE_ANALYST, access.ROLE_ANALYST) is True
    assert access.can(access.ROLE_ANALYST, access.ROLE_EDITOR) is False
    assert access.can(access.ROLE_ANALYST, access.ROLE_OWNER) is False


def test_unknown_role_passes_nowhere():
    """Роль из будущей версии после отката должна упереться в отказ.

    Пропустить её «на всякий случай» значило бы выдать неизвестной учётке
    права по умолчанию.
    """
    for needed in access.ALL_ROLES:
        assert access.can("superadmin", needed) is False
        assert access.can(None, needed) is False
        assert access.can("", needed) is False


# --- запрет по умолчанию ---


def test_unknown_path_requires_owner():
    """ГЛАВНЫЙ ТЕСТ ФАЙЛА.

    Страница, добавленная через полгода и забытая в политике, не должна
    оказаться открытой редактору. Худшее, что произойдёт при запрете, —
    сотрудник упрётся в отказ и спросит.
    """
    assert access.required_role("/что-то-новое") == access.ROLE_OWNER
    assert access.required_role("/api/secret-stuff") == access.ROLE_OWNER


@pytest.mark.parametrize(
    "path",
    ["/settings", "/secrets", "/telethon-sessions", "/audit", "/export", "/users"],
)
def test_sensitive_paths_are_owner_only(path):
    assert access.required_role(path) == access.ROLE_OWNER
    assert access.can(access.ROLE_EDITOR, access.required_role(path)) is False


@pytest.mark.parametrize(
    "path",
    ["/sources", "/moderation", "/broadcasts", "/segments", "/ad-requests"],
)
def test_content_paths_are_open_to_editor(path):
    assert access.can(access.ROLE_EDITOR, access.required_role(path)) is True
    assert access.can(access.ROLE_ANALYST, access.required_role(path)) is False


@pytest.mark.parametrize("path", ["/", "/stats", "/mediakit", "/growth"])
def test_read_only_paths_are_open_to_analyst(path):
    assert access.can(access.ROLE_ANALYST, access.required_role(path)) is True


# --- разбор пути ---


def test_longest_prefix_wins():
    """`/guardian/settings` строже, чем `/guardian`.

    Если бы побеждал первый подошедший префикс, редактор получил бы доступ
    к настройкам Guardian — то есть к порогам банов и стоп-словам.
    """
    assert access.required_role("/guardian") == access.ROLE_EDITOR
    assert access.required_role("/guardian/settings") == access.ROLE_OWNER


def test_root_does_not_match_everything():
    """Корень — не префикс для всего.

    Иначе `/` совпал бы с любой страницей и открыл аналитику всю админку.
    """
    assert access.required_role("/") == access.ROLE_ANALYST
    assert access.required_role("/settings") == access.ROLE_OWNER


def test_prefix_does_not_match_partial_word():
    """`/settings-export` — не `/settings`.

    Совпадение по началу строки без проверки границы дало бы доступ к
    похоже названной странице.
    """
    assert access.required_role("/settings-export") == access.ROLE_OWNER  # запрет
    assert access.required_role("/stats") == access.ROLE_ANALYST
    assert access.required_role("/statsomething") == access.ROLE_OWNER


def test_subpaths_inherit_the_rule():
    assert access.required_role("/sources/42") == access.ROLE_EDITOR
    assert access.required_role("/contacts/999/tags") == access.ROLE_EDITOR


def test_exempt_paths_are_recognised():
    for path in ("/login", "/logout", "/static/style.css", "/lang/en"):
        assert access.is_exempt(path) is True
    assert access.is_exempt("/settings") is False
