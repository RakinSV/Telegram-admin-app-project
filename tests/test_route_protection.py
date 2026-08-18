"""Ни один роут не остаётся без защиты по недосмотру (аудит 2026-08-19).

ЗАЧЕМ. В админке 171 роут, и защита у них разная по устройству: страницы
владельца — сессией (`require_login`), публичный API — ключом (`require_key`),
первичная настройка — одноразовым токеном (`require_setup_token`), Mini App —
подписью Telegram внутри обработчика. Защита вешается на РОУТЕР, и достаточно
одного нового роутера, собранного без `dependencies=[...]`, чтобы страница
молча открылась миру. Ошибка тихая: тесты фичи проходят, страница работает,
никто не замечает.

КАК УСТРОЕНА ПРОВЕРКА. Список публичных роутов задан ЯВНО и с указанием, чем
именно каждый защищён вместо сессии. Новый роут без защиты в этот список не
попадёт и уронит тест: чтобы его туда добавить, придётся вписать причину, то
есть подумать. Это дешевле, чем обнаружить открытую страницу в бою.
"""

from __future__ import annotations

from fastapi.routing import APIRoute

from tg_repost.webui.app import create_app

# Роут -> чем защищён вместо сессии владельца. Пустая строка означала бы
# «ничем», и такого здесь быть не должно ни у одной строки.
PUBLIC_BY_DESIGN = {
    # Вход и выход: до входа сессии нет по определению.
    ("/login", "GET"): "форма входа; попытки ограничены блокировкой по адресу",
    ("/login", "POST"): "проверка пароля и есть аутентификация",
    ("/logout", "POST"): "выход без сессии безвреден",
    # Язык интерфейса — не данные.
    ("/lang/{code}", "GET"): "переключение языка, ничего не читает и не пишет",
    # Здоровье процесса: его дёргает docker healthcheck, у которого сессии нет.
    ("/health", "GET"): "только статусы компонентов, без данных",
    # Первичная настройка: одноразовый токен из логов, админа ещё не существует.
    ("/setup", "GET"): "require_setup_token",
    ("/setup", "POST"): "require_setup_token",
    ("/setup/telethon", "GET"): "require_setup_token",
    ("/setup/telethon", "POST"): "require_setup_token",
    ("/setup/telethon/cancel", "POST"): "require_setup_token",
    ("/setup/telethon/code", "GET"): "require_setup_token",
    ("/setup/telethon/code", "POST"): "require_setup_token",
    ("/setup/telethon/password", "GET"): "require_setup_token",
    ("/setup/telethon/password", "POST"): "require_setup_token",
    # Публичный API (F73): ключ вместо сессии, на запись — отдельное право.
    ("/api/v1/ping", "GET"): "require_key",
    ("/api/v1/posts", "GET"): "require_key",
    ("/api/v1/posts", "POST"): "require_write",
    ("/api/v1/stats", "GET"): "require_key",
    ("/api/v1/audience", "GET"): "require_key",
    # Mini App (F74): страница-скорлупа без данных, всё содержимое приходит
    # вторым запросом и только по подписи Telegram (`initData`): HMAC на
    # токене бота плюс проверка свежести. Сессии здесь быть не может —
    # участник Telegram в админке не заводится.
    ("/app", "GET"): "пустая оболочка, данных не отдаёт",
    ("/app/data", "POST"): "подпись Telegram initData внутри обработчика",
}


def _api_routes():
    """Все роуты приложения, включая вложенные в подключённые роутеры."""
    app = create_app()
    routes = []
    for entry in app.routes:
        # FastAPI оборачивает подключённые роутеры, и их роуты лежат внутри.
        original = getattr(entry, "original_router", None)
        if original is not None:
            routes.extend(r for r in original.routes if isinstance(r, APIRoute))
        elif isinstance(entry, APIRoute):
            routes.append(entry)
    return routes


def _dependency_names(route: APIRoute) -> set[str]:
    return {
        getattr(dep.call, "__name__", "?")
        for dep in (route.dependant.dependencies or [])
    }


def test_every_route_is_protected_or_listed_as_public():
    """Главная проверка: новый роут без защиты роняет тест."""
    unlisted = []
    for route in _api_routes():
        names = _dependency_names(route)
        if "require_login" in names:
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            if (route.path, method) not in PUBLIC_BY_DESIGN:
                unlisted.append(f"{method} {route.path} (зависимости: {sorted(names) or '—'})")

    assert not unlisted, (
        "роуты без входа и без записи в списке публичных:\n" + "\n".join(unlisted)
        + "\nЕсли роут действительно публичный, впиши его в PUBLIC_BY_DESIGN "
          "вместе с тем, чем он защищён вместо сессии."
    )


def test_public_list_has_no_stale_entries():
    """Обратная сторона: список публичных не должен хранить роуты, которых
    больше нет. Иначе он превращается в свалку, где новую дыру не заметить."""
    existing = set()
    for route in _api_routes():
        for method in route.methods - {"HEAD", "OPTIONS"}:
            existing.add((route.path, method))

    stale = sorted(key for key in PUBLIC_BY_DESIGN if key not in existing)

    assert not stale, f"в списке публичных остались несуществующие роуты: {stale}"


def test_api_routes_require_a_key():
    """Публичный API отдаёт данные наружу и обязан спрашивать ключ — на
    чтении `require_key`, на записи `require_write`."""
    unguarded = []
    for route in _api_routes():
        if not route.path.startswith("/api/"):
            continue
        names = _dependency_names(route)
        if not names & {"require_key", "require_write"}:
            unguarded.append(route.path)

    assert not unguarded, f"API-роуты без проверки ключа: {unguarded}"


def test_setup_routes_require_the_setup_token():
    """Первичная настройка заводит АДМИНА. Открытый /setup — это чужой
    администратор в системе, а не неудобство."""
    unguarded = []
    for route in _api_routes():
        if not route.path.startswith("/setup"):
            continue
        if "require_setup_token" not in _dependency_names(route):
            unguarded.append(route.path)

    assert not unguarded, f"роуты настройки без одноразового токена: {unguarded}"
