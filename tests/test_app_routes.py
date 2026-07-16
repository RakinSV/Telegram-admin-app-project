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

from tg_repost.db.models import AdminUser, AppSetting, Post, PostStat, Secret, Source, TelethonSession
from tg_repost.db.session import session_scope
from tg_repost.webui import app as app_module
from tg_repost.webui import audit, auth, setup_token
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
        session.query(TelethonSession).delete()
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


def _covers_form(**overrides: str) -> dict:
    base = {
        "enable_auto_cover": "on",
        "cover_strategy": "unsplash",
        "unsplash_api_url": "https://api.unsplash.com/photos/random",
        "comfyui_base_url": "",
        "comfyui_workflow_path": "",
        "comfyui_positive_node_id": "",
        "comfyui_poll_attempts": "10",
        "comfyui_poll_interval_seconds": "2.0",
    }
    base.update(overrides)
    return base


def test_settings_save_cover_strategy_rejects_value_outside_choices():
    """Регрессия (code-ревью): cover_strategy был обычным str без choices —
    опечатка вида "ComfyUI" молча проходила бы валидацию (любая непустая
    строка) и код (`if settings.cover_strategy == "comfyui"`) тихо всегда
    попадал бы в ветку unsplash."""
    client = _client()
    _bootstrap(client)
    r = client.post("/settings/covers", data=_covers_form(cover_strategy="ComfyUI"))
    assert r.status_code == 400
    assert "Стратегия" in r.text or "должно быть одним из" in r.text


def test_settings_save_cover_strategy_accepts_valid_choice():
    client = _client()
    _bootstrap(client)
    r = client.post(
        "/settings/covers", data=_covers_form(cover_strategy="comfyui"),
        follow_redirects=False,
    )
    assert r.status_code == 303
    r = client.get("/settings")
    assert "comfyui" in r.text


def test_settings_save_cover_strategy_accepts_openai_choice():
    # F18-доп.: третья стратегия — генерация через уже настроенный
    # OpenAI-совместимый провайдер рерайта, без своего API-ключа.
    client = _client()
    _bootstrap(client)
    r = client.post(
        "/settings/covers",
        data=_covers_form(
            cover_strategy="openai",
            cover_openai_model="black-forest-labs/flux.2-klein-4b",
            cover_image_prompt_template="Cover for: {post_text}",
        ),
        follow_redirects=False,
    )
    assert r.status_code == 303
    r = client.get("/settings")
    assert "black-forest-labs/flux.2-klein-4b" in r.text


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


def test_secrets_clear_route_removes_saved_secret_via_http():
    """Регрессия (жалоба пользователя): на /secrets не было способа
    удалить сохранённый секрет (прокси и т.д.) — отправка формы с пустым
    value молча ничего не делала. Теперь есть отдельная кнопка/роут."""
    client = _client()
    _bootstrap(client)
    client.post("/secrets/telethon_proxy_url", data={"value": "socks5://1.2.3.4:1080"})
    r = client.get("/settings")
    assert "1.2.3.4:1080" not in r.text  # write-only, введённое значение не отдаётся обратно
    # "Telethon SOCKS5 ..." встречается на странице трижды (в описании группы,
    # в <strong>-заголовке строки секрета и ещё раз внутри confirm() у кнопки
    # «Очистить») — якорем берём именно <strong>-тег, он однозначен.
    anchor = "<strong>Telethon SOCKS5 Proxy URL (socks5://[user:pass@]host:port)</strong>"
    section = r.text.split(anchor)[1][:600]
    assert "не задан" not in section  # секрет сохранён — статус "ok"

    r = client.post("/secrets/telethon_proxy_url/clear", follow_redirects=False)
    assert r.status_code == 303

    r = client.get("/settings")
    section = r.text.split(anchor)[1][:600]
    assert "не задан" in section


def test_secrets_get_redirects_to_settings():
    """Старая ссылка /secrets (закладка, внешняя ссылка) не должна 404 —
    секреты и настройки объединены на одной странице /settings."""
    client = _client()
    _bootstrap(client)
    r = client.get("/secrets", follow_redirects=False)
    assert r.status_code == 308
    assert r.headers["location"] == "/settings"


def test_secrets_reveal_with_correct_password_shows_plaintext():
    client = _client()
    _bootstrap(client, password="reveal-test-password-1")
    client.post("/secrets/telethon_proxy_url", data={"value": "socks5://9.9.9.9:1080"})

    r = client.post(
        "/secrets/telethon_proxy_url/reveal",
        data={"password": "reveal-test-password-1"},
    )
    assert r.status_code == 200
    assert "socks5://9.9.9.9:1080" in r.text


def test_secrets_reveal_with_wrong_password_does_not_show_plaintext():
    client = _client()
    _bootstrap(client, password="reveal-test-password-2")
    client.post("/secrets/telethon_proxy_url", data={"value": "socks5://9.9.9.9:1080"})

    r = client.post(
        "/secrets/telethon_proxy_url/reveal",
        data={"password": "totally-wrong-password"},
    )
    assert r.status_code == 401
    assert "socks5://9.9.9.9:1080" not in r.text
    assert "Неверный пароль" in r.text


def test_secrets_reveal_records_audit_entry():
    client = _client()
    _bootstrap(client, password="reveal-test-password-3")
    client.post("/secrets/telethon_proxy_url", data={"value": "socks5://9.9.9.9:1080"})
    _clear_audit_before = len(audit.list_audit_log())
    client.post(
        "/secrets/telethon_proxy_url/reveal",
        data={"password": "reveal-test-password-3"},
    )
    entries = audit.list_audit_log()
    assert len(entries) > _clear_audit_before
    assert entries[0].action == "secret_reveal"
    assert entries[0].target == "telethon_proxy_url"
    assert entries[0].detail is None  # НИКОГДА не хранить само значение в аудит-логе


def test_secrets_reveal_locks_out_after_repeated_wrong_passwords():
    client = _client()
    _bootstrap(client, password="reveal-test-password-4")
    client.post("/secrets/telethon_proxy_url", data={"value": "socks5://9.9.9.9:1080"})
    for _ in range(auth._MAX_FAILED_ATTEMPTS):
        client.post(
            "/secrets/telethon_proxy_url/reveal",
            data={"password": "wrong"},
        )
    r = client.post(
        "/secrets/telethon_proxy_url/reveal",
        data={"password": "reveal-test-password-4"},  # даже верный пароль заблокирован
    )
    assert r.status_code == 429
    assert "socks5://9.9.9.9:1080" not in r.text


def test_sources_create_and_list_round_trip():
    client = _client()
    _bootstrap(client)
    r = client.post("/sources", data={"channel": "@integration_test_chan"}, follow_redirects=False)
    assert r.status_code == 303
    r = client.get("/sources")
    assert r.status_code == 200
    assert "integration_test_chan" in r.text


def test_sources_create_bulk_comma_and_newline_separated():
    """Фича (жалоба пользователя): вставка нескольких каналов за раз."""
    client = _client()
    _bootstrap(client)
    r = client.post(
        "/sources",
        data={"channel": "@bulk_a, @bulk_b\n@bulk_c"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    r = client.get("/sources")
    for name in ("bulk_a", "bulk_b", "bulk_c"):
        assert name in r.text


def test_sources_create_bulk_calls_restart_once(monkeypatch):
    """Массовая вставка нескольких НОВЫХ каналов — рестарт listener'а
    должен произойти ровно один раз, а не по разу на каждый источник."""
    from tg_repost.webui import crud_routes

    client = _client()
    _bootstrap(client)

    calls = []

    async def _fake_restart():
        calls.append(1)

    monkeypatch.setattr(crud_routes, "restart_telethon_listener", _fake_restart)
    r = client.post(
        "/sources",
        data={"channel": "@restart_once_a, @restart_once_b, @restart_once_c"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert calls == [1]


def test_sources_create_bulk_rejects_too_many():
    client = _client()
    _bootstrap(client)
    many = ",".join(f"@toomany{i}" for i in range(101))
    r = client.post("/sources", data={"channel": many}, follow_redirects=False)
    assert r.status_code == 400


def test_sources_create_no_restart_when_already_active(monkeypatch):
    """Регресс-тест (аудит ведения групп, раунд 2): повторная отправка
    формы для УЖЕ активного источника (double-submit) ничего не меняет в
    составе слушаемых каналов — не должна дёргать restart_telethon_listener."""
    from tg_repost.webui import crud_routes

    client = _client()
    _bootstrap(client)
    client.post("/sources", data={"channel": "@already_active_chan"}, follow_redirects=False)

    calls = []

    async def _fake_restart():
        calls.append(1)

    monkeypatch.setattr(crud_routes, "restart_telethon_listener", _fake_restart)
    r = client.post("/sources", data={"channel": "@already_active_chan"}, follow_redirects=False)
    assert r.status_code == 303
    assert calls == []


def test_sources_create_restart_failure_does_not_break_response(monkeypatch):
    """Регресс-тест: источник уже закоммичен в БД к моменту вызова
    restart_telethon_listener() — его сбой не должен превращать успешное
    добавление источника в ошибку на экране."""
    from tg_repost import sources_repo
    from tg_repost.webui import crud_routes

    async def _boom():
        raise RuntimeError("Telegram недоступен")

    monkeypatch.setattr(crud_routes, "restart_telethon_listener", _boom)
    client = _client()
    _bootstrap(client)
    r = client.post(
        "/sources", data={"channel": "@restart_fails_chan"}, follow_redirects=False,
    )
    assert r.status_code == 303
    assert sources_repo.find_source_by_username("restart_fails_chan") is not None


def test_source_detail_shows_targets_as_checkboxes():
    """Новый роутинг (аудит UX): цели выбираются чекбоксами, а не вводом
    chat_id вручную — на странице источника должны быть чекбоксы целей."""
    from tg_repost import sources_repo, targets_repo
    client = _client()
    _bootstrap(client)
    src, _ = sources_repo.add_source("@routing_src")
    targets_repo.add_target(-1001111, "Канал А")
    targets_repo.add_target(-1002222, "Канал Б")

    r = client.get(f"/sources/{src.id}")
    assert r.status_code == 200
    assert 'type="checkbox"' in r.text
    assert "Канал А" in r.text and "Канал Б" in r.text
    assert 'value="-1001111"' in r.text


def test_source_update_checkboxes_map_to_target_chat_ids():
    """Отмеченные чекбоксы целей должны сохраниться как CSV target_chat_ids
    источника (маршрут «из этого источника — в эти группы»)."""
    from tg_repost import sources_repo, targets_repo
    client = _client()
    _bootstrap(client)
    src, _ = sources_repo.add_source("@routing_src2")
    targets_repo.add_target(-1003333, "В")
    targets_repo.add_target(-1004444, "Г")

    # Отмечаем две цели — httpx кодирует list-значение как повторяющиеся
    # form-поля target_chat_ids=-1003333&target_chat_ids=-1004444.
    r = client.post(
        f"/sources/{src.id}",
        data={"style_profile": "", "enrich_mode": "default",
              "target_chat_ids": ["-1003333", "-1004444"]},
        follow_redirects=False,
    )
    assert r.status_code == 303
    updated = sources_repo.get_source(src.id)
    assert set(updated.target_chat_ids.split(",")) == {"-1003333", "-1004444"}


def test_source_update_no_checkboxes_clears_targets_to_all():
    """Ни одна цель не отмечена — target_chat_ids очищается (публикация во
    все активные), а не остаётся старое значение."""
    from tg_repost import sources_repo, targets_repo
    client = _client()
    _bootstrap(client)
    src, _ = sources_repo.add_source("@routing_src3")
    targets_repo.add_target(-1005555, "Д")
    sources_repo.set_source_targets(src.id, "-1005555")

    r = client.post(
        f"/sources/{src.id}",
        data={"style_profile": "", "enrich_mode": "default"},  # без target_chat_ids
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert sources_repo.get_source(src.id).target_chat_ids is None


def test_source_backfill_without_running_components_shows_error():
    """Жалоба пользователя: "надо чтобы это делалось из админки" — новая
    кнопка на source_detail. Компоненты не запущены (обычное состояние в
    этих тестах, start_components замокан на no-op) — понятная ошибка,
    не 500/исключение."""
    from tg_repost import sources_repo
    client = _client()
    _bootstrap(client)
    src, _ = sources_repo.add_source("@backfill_src1")

    r = client.post(f"/sources/{src.id}/backfill", data={"limit": "10"})
    assert r.status_code == 400
    assert "Компоненты не запущены" in r.text


def test_source_backfill_rejects_out_of_range_limit():
    from tg_repost import sources_repo
    client = _client()
    _bootstrap(client)
    src, _ = sources_repo.add_source("@backfill_src2")

    r = client.post(f"/sources/{src.id}/backfill", data={"limit": "0"})
    assert r.status_code == 400
    assert "от 1 до 200" in r.text

    r = client.post(f"/sources/{src.id}/backfill", data={"limit": "not-a-number"})
    assert r.status_code == 400


def test_source_backfill_success_redirects_with_count():
    """Успешный сценарий: components "запущены" (подсовываем фиктивный
    tele_client в общий супервизор-синглтон), `listener.backfill_source`
    замокан (реальный сетевой Telethon-вызов тут не нужен и невозможен)."""
    from unittest.mock import AsyncMock

    from tg_repost import sources_repo
    from tg_repost.webui.supervisor import get_components

    client = _client()
    _bootstrap(client)
    src, _ = sources_repo.add_source("@backfill_src3")

    components = get_components()
    components.tele_client = object()  # достаточно "не None" для проверки в роуте
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "tg_repost.telegram.listener.backfill_source",
                AsyncMock(return_value=7),
            )
            r = client.post(
                f"/sources/{src.id}/backfill", data={"limit": "50"},
                follow_redirects=False,
            )
        assert r.status_code == 303
        assert r.headers["location"] == f"/sources/{src.id}?backfilled=7"

        r = client.get(f"/sources/{src.id}?backfilled=7")
        assert "Обработано сообщений: 7" in r.text
    finally:
        components.tele_client = None  # не протекать в остальные тесты файла


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


def test_telethon_sessions_add_list_disable_round_trip():
    """F26: страница управления доп. Telethon-сессиями — маска, не полное
    значение, показывается в списке; значение никогда не возвращается."""
    client = _client()
    _bootstrap(client)

    r = client.post(
        "/telethon-sessions",
        data={"label": "account-2", "session_string": "1BVtsOK-fake-session-value"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = client.get("/telethon-sessions")
    assert r.status_code == 200
    assert "account-2" in r.text
    assert "1BVtsOK-fake-session-value" not in r.text  # write-only — не отдаётся обратно

    from tg_repost import telethon_sessions_repo
    row = telethon_sessions_repo.list_sessions()[0]

    r = client.post(f"/telethon-sessions/{row.id}/disable", follow_redirects=False)
    assert r.status_code == 303
    r = client.get("/telethon-sessions")
    assert "нет" in r.text  # активна: нет


def test_telethon_sessions_rejects_empty_session_string():
    client = _client()
    _bootstrap(client)
    r = client.post("/telethon-sessions", data={"label": "account-2", "session_string": "   "})
    assert r.status_code == 400


def test_moderation_detail_hides_target_routing_for_already_posted_post():
    """Регресс-тест (аудит ведения групп, раунд 2): `/moderation/{id}`
    доступен по прямой ссылке для ЛЮБОГО поста, не только для ожидающих
    модерации — например, /stats линкует на "топ-пост", у которого
    status=posted. Блок "Опубликуется в" не должен показываться для уже
    опубликованного (или отклонённого) поста — это относится только к
    постам, публикация которых ещё предстоит. Явно создаём свою активную
    цель (а не полагаемся на "в тестовой БД по умолчанию целей нет" — это
    ломается под полным прогоном сьюта из-за общей БД между файлами)."""
    from tg_repost import targets_repo
    from tg_repost.db.models import PostKind, PostStatus

    client = _client()
    _bootstrap(client)
    targets_repo.add_target(-100987654, "Regression Test Target")

    with session_scope() as session:
        posted = Post(
            kind=PostKind.SOURCE, original_text="orig", rewritten_text="v0",
            status=PostStatus.POSTED,
        )
        session.add(posted)
        pending = Post(
            kind=PostKind.SOURCE, original_text="orig", rewritten_text="v0",
            status=PostStatus.PENDING_APPROVAL,
        )
        session.add(pending)
        session.flush()
        posted_id, pending_id = posted.id, pending.id

    r_posted = client.get(f"/moderation/{posted_id}")
    assert r_posted.status_code == 200
    assert "Опубликуется в" not in r_posted.text
    assert "Публиковать некуда" not in r_posted.text

    r_pending = client.get(f"/moderation/{pending_id}")
    assert r_pending.status_code == 200
    # Пост ещё не опубликован — активная цель есть, ожидаем "Опубликуется в".
    assert "Опубликуется в" in r_pending.text
