"""Роли и доступ к страницам админки (F37).

ТРИ РОЛИ, И ОНИ УПОРЯДОЧЕНЫ:

* **owner** — всё, включая секреты и настройки. Секреты у нас это токены
  ботов и session string, то есть полный доступ к Telegram-аккаунту, а не к
  контенту — поэтому граница между владельцем и остальными проходит именно
  здесь;
* **editor** — контент и модерация: посты, источники, рассылки, заявки.
  Всё, ради чего сотрудника и нанимают, и ничего сверх;
* **analyst** — только чтение статистики. Роль для того, кто считает
  эффективность и не должен иметь возможности что-то опубликовать.

ЗАПРЕТ ПО УМОЛЧАНИЮ — главное свойство этого модуля. Путь, не описанный в
политике, доступен ТОЛЬКО владельцу. Это значит, что новая страница,
добавленная через полгода и забытая здесь, не окажется случайно открытой
редактору: худшее, что произойдёт, — редактор упрётся в отказ и спросит.
Обратный порядок («не описано — значит можно») однажды тихо откроет
сотруднику страницу секретов.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

ROLE_OWNER = "owner"
ROLE_EDITOR = "editor"
ROLE_ANALYST = "analyst"

ALL_ROLES = (ROLE_OWNER, ROLE_EDITOR, ROLE_ANALYST)

# Чем больше число, тем больше прав. Сравнение по уровню, а не по списку
# разрешений: три роли строго вложены друг в друга, и городить матрицу
# «роль × право» ради этого значило бы усложнить проверку без выигрыша.
_LEVEL = {ROLE_ANALYST: 1, ROLE_EDITOR: 2, ROLE_OWNER: 3}

# Минимальная роль по префиксу пути. Порядок важен: берётся САМОЕ ДЛИННОЕ
# совпадение, поэтому `/guardian/settings` (owner) перекрывает `/guardian`
# (editor), а не наоборот.
_POLICY: dict[str, str] = {
    # --- только владелец: настройки, секреты, доступ к аккаунту ---
    "/settings": ROLE_OWNER,
    "/secrets": ROLE_OWNER,
    "/telethon-sessions": ROLE_OWNER,
    "/telethon-login": ROLE_OWNER,
    "/components": ROLE_OWNER,
    "/audit": ROLE_OWNER,
    "/export": ROLE_OWNER,
    "/users": ROLE_OWNER,
    "/guardian/settings": ROLE_OWNER,
    # --- редактор: контент и модерация ---
    "/sources": ROLE_EDITOR,
    "/targets": ROLE_EDITOR,
    "/moderation": ROLE_EDITOR,
    "/ads": ROLE_EDITOR,
    "/polls": ROLE_EDITOR,
    "/invites": ROLE_EDITOR,
    "/contacts": ROLE_EDITOR,
    "/segments": ROLE_EDITOR,
    "/broadcasts": ROLE_EDITOR,
    "/ad-requests": ROLE_EDITOR,
    "/guardian": ROLE_EDITOR,
    # --- аналитик: только смотреть ---
    "/": ROLE_ANALYST,
    "/stats": ROLE_ANALYST,
    "/growth": ROLE_ANALYST,
    "/mediakit": ROLE_ANALYST,
    "/logs": ROLE_ANALYST,
}

# Пути, доступные до входа или не относящиеся к ролям вовсе.
_EXEMPT = ("/login", "/logout", "/setup", "/lang", "/static", "/health")


def required_role(path: str) -> str:
    """Минимальная роль для пути. Незнакомый путь → владелец (запрет).

    Корень обрабатывается отдельно: как префикс `/` совпал бы со всем
    подряд и открыл бы аналитику любую страницу.
    """
    if path == "/":
        return _POLICY["/"]

    best = ""
    for prefix in _POLICY:
        if prefix == "/":
            continue
        if path == prefix or path.startswith(prefix + "/"):
            if len(prefix) > len(best):
                best = prefix
    if not best:
        # Запрет по умолчанию — см. docstring модуля.
        return ROLE_OWNER
    return _POLICY[best]


def is_exempt(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in _EXEMPT)


def can(role: str | None, needed: str) -> bool:
    """Хватает ли роли. Неизвестная роль не проходит никуда.

    Неизвестная — это, например, роль из будущей версии после отката: такая
    учётка должна упереться в отказ, а не получить права по умолчанию.
    """
    if role not in _LEVEL:
        return False
    return _LEVEL[role] >= _LEVEL[needed]


def require_access(request: Request) -> None:
    """Зависимость роутера: пустить, если роль позволяет.

    Ставится ПОСЛЕ `require_login`, поэтому здесь уже известно, что человек
    вошёл; остаётся вопрос, что ему можно.
    """
    path = request.url.path
    if is_exempt(path):
        return
    role = request.session.get("role")
    if not can(role, required_role(path)):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
