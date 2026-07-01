"""Интеграционные тесты HTTP-роутов веб-админки через `TestClient` (F23,
аудит Фазы 5) — раньше `app.py`/`crud_routes.py` не были покрыты НИ ОДНИМ
тестом (весь остальной набор тестирует модули-хелперы в изоляции), поэтому
опечатка в роутинге или в `Depends(...)` не была бы поймана ничем. Здесь —
минимальный, но реальный сквозной флоу: бутстрап → логин → настройки → CRUD.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from tg_repost.db.models import AdminUser, AppSetting, Post, PostStat, Secret, Source
from tg_repost.db.session import session_scope
from tg_repost.webui import app as app_module
from tg_repost.webui import auth, setup_token
from tg_repost.webui.app import create_app
from tg_repost.webui.settings_store import SETTINGS_GROUPS


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Изоляция между тестами этого файла:

    1. CWD переключается на временный каталог — генерация WEBUI_MASTER_KEY/
       WEBUI_SESSION_SECRET пишет `.env` относительно CWD (см.
       test_settings_store.py — тот же паттерн, найден однажды случайно
       записавший ключ в `.env` корня проекта без этой изоляции).
    2. Таблицы admin_users/app_settings/secrets/sources чистятся — общий
       sqlite-engine-синглтон на весь pytest-процесс (см. tests/conftest.py).
    3. Модульные синглтоны (`setup_token`, `auth._failed_attempts`)
       сбрасываются.
    4. `start_components` подменяется на no-op — `tests/conftest.py` задаёт
       фиктивные, но "непустые" TG_API_ID/HASH/BOT_TOKEN/OWNER_ID/OPENAI_KEY
       на весь pytest-процесс (нужны, чтобы `Settings()` вообще
       конструировался для остальных тестов), из-за чего
       `is_minimally_configured` здесь всегда True и `/setup` реально
       попытался бы поднять Telethon-клиент с мусорными кредами. Здесь
       тестируется HTTP-роутинг `/setup`, а не поднятие Telegram-компонентов
       (то уже покрыто моками в test_supervisor.py).
    """
    monkeypatch.chdir(tmp_path)
    with session_scope() as session:
        session.query(AdminUser).delete()
        session.query(AppSetting).delete()
        session.query(Secret).delete()
        session.query(Source).delete()
    os.environ.pop("WEBUI_MASTER_KEY", None)
    os.environ.pop("WEBUI_SESSION_SECRET", None)
    setup_token._token = None
    auth._failed_attempts.clear()

    async def _noop_start_components(settings):
        del settings

    monkeypatch.setattr(app_module, "start_components", _noop_start_components)

    from tg_repost.config import invalidate_settings_cache
    invalidate_settings_cache()
    yield
    setup_token._token = None
    auth._failed_attempts.clear()
    invalidate_settings_cache()


def _client() -> TestClient:
    return TestClient(create_app())


def _bootstrap(client: TestClient, password: str = "smoke-test-password-123") -> None:
    """Пройти /setup (с валидным токеном) и залогиниться — общий пролог для
    тестов, которым нужен уже настроенный админ."""
    token = setup_token.get_or_create_setup_token()
    r = client.post(
        f"/setup?token={token}",
        data={"password": password, "password_confirm": password},
        follow_redirects=False,
    )
    assert r.status_code == 303, (r.status_code, r.text[:500])
    r = client.post("/login", data={"password": password}, follow_redirects=False)
    assert r.status_code == 303, (r.status_code, r.text[:500])


def test_unauthenticated_access_redirects_to_login():
    client = _client()
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_setup_requires_token_before_bootstrap():
    client = _client()
    r = client.get("/setup")
    assert r.status_code == 403
    assert "токен" in r.text.lower()


def test_setup_accessible_with_valid_token():
    client = _client()
    token = setup_token.get_or_create_setup_token()
    r = client.get(f"/setup?token={token}")
    assert r.status_code == 200


def test_setup_token_unlocks_session_for_subsequent_requests():
    """Токен нужно передать один раз — дальше визард работает по сессии
    без повторной передачи `?token=` в каждой ссылке."""
    client = _client()
    token = setup_token.get_or_create_setup_token()
    client.get(f"/setup?token={token}")
    r = client.get("/setup/telethon")
    assert r.status_code == 200


def test_full_bootstrap_login_dashboard_flow():
    client = _client()
    _bootstrap(client)
    r = client.get("/")
    assert r.status_code == 200
    assert "Дашборд" in r.text or "дашборд" in r.text.lower()


def test_second_setup_after_bootstrap_redirects_to_login_not_500():
    """Регрессия: TOCTOU-гонка на /setup (найдено при security-аудите Фазы
    5) — второй POST /setup после того, как админ уже создан, не должен
    падать 500 (IntegrityError), а должен чисто редиректить на /login."""
    client = _client()
    _bootstrap(client)
    token = setup_token.get_or_create_setup_token()
    r = client.post(
        f"/setup?token={token}",
        data={"password": "another-password-123", "password_confirm": "another-password-123"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_login_lockout_after_failed_attempts():
    client = _client()
    _bootstrap(client)
    logout_client = _client()  # тот же процесс/auth-состояние, свежий cookie jar
    for _ in range(5):
        r = logout_client.post("/login", data={"password": "wrong-password"})
        assert r.status_code == 401
    r = logout_client.post("/login", data={"password": "wrong-password"})
    assert r.status_code == 429


def test_settings_save_round_trip():
    client = _client()
    _bootstrap(client)
    group = SETTINGS_GROUPS[0]
    assert group.key == "telegram"
    r = client.post(
        "/settings/telegram",
        data={"tg_api_id": "777", "tg_owner_user_id": "888"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    r = client.get("/settings")
    assert "777" in r.text
    assert "888" in r.text


def test_settings_save_invalid_number_returns_clean_400():
    """Регрессия: `_coerce_form_value` раньше бросал необработанный
    ValueError на нечисловой ввод — голый 500 вместо формы с ошибкой
    (найдено при security-аудите Фазы 5)."""
    client = _client()
    _bootstrap(client)
    r = client.post(
        "/settings/telegram",
        data={"tg_api_id": "not-a-number", "tg_owner_user_id": "888"},
    )
    assert r.status_code == 400
    assert "error" in r.text.lower() or "Некорректн" in r.text


def test_settings_save_invalid_number_does_not_partially_apply():
    """Регрессия: раньше поля сохранялись по одному в цикле — плохое
    значение в одном поле не должно оставлять СОСЕДНИЕ поля из той же формы
    частично применёнными."""
    client = _client()
    _bootstrap(client)
    client.post("/settings/telegram", data={"tg_api_id": "111", "tg_owner_user_id": "222"})
    client.post(
        "/settings/telegram",
        data={"tg_api_id": "999", "tg_owner_user_id": "not-a-number"},
    )
    r = client.get("/settings")
    # Ни одно из двух полей группы не должно было измениться на 999 —
    # обе части формы валидируются ДО записи чего-либо.
    assert "999" not in r.text
    assert "111" in r.text
    assert "222" in r.text


def test_sources_create_and_list_round_trip():
    client = _client()
    _bootstrap(client)
    r = client.post("/sources", data={"channel": "@integration_test_chan"}, follow_redirects=False)
    assert r.status_code == 303
    r = client.get("/sources")
    assert r.status_code == 200
    assert "integration_test_chan" in r.text


def test_best_times_apply_without_data_redirects_with_applied_zero():
    """F19 доделка: кнопка «Применить сейчас» на /stats/best-times не должна
    падать, если данных недостаточно — просто редиректит без изменений.
    Явно чистим posts/post_stats — общий sqlite-engine на весь
    pytest-процесс, другие файлы (test_smart_schedule.py и т.д.) могли
    оставить там опубликованные посты, что дало бы enough_data=True здесь."""
    with session_scope() as session:
        session.query(PostStat).delete()
        session.query(Post).delete()
    client = _client()
    _bootstrap(client)
    r = client.get("/stats/best-times")
    assert r.status_code == 200
    r = client.post("/stats/best-times/apply", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/stats/best-times?applied=0"


def test_protected_route_rejects_expired_session(monkeypatch):
    """Регрессия: сессия без временных меток (или просроченная) должна
    отклоняться `require_login`, а не приниматься бессрочно (найдено при
    security-аудите Фазы 5)."""
    client = _client()
    _bootstrap(client)
    r = client.get("/")
    assert r.status_code == 200

    # Истечь last_seen искусственно, не дожидаясь реальных 12 часов.
    real_time = auth.time.time
    monkeypatch.setattr(auth.time, "time", lambda: real_time() + 13 * 3600)
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"
