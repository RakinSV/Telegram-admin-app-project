"""Интеграционные тесты HTTP-роутов управления Guardian из веб-админки
tg_repost (`/guardian*`, `webui/guardian_routes.py`) — тот же паттерн, что
`test_app_routes.py`: реальный `TestClient`, не моки на уровне функций.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from guardian.config import invalidate_settings_cache as guardian_invalidate_cache
from guardian.db.models import AllowedDomain, BotConfig, Member, ModerationLog, StopWord, TrustedUser
from guardian.db.session import session_scope as guardian_session_scope
from tg_repost.db.models import AdminUser, AppSetting, Secret, Source, TargetGroup, TelethonSession
from tg_repost.db.session import session_scope
from tg_repost.webui import app as app_module
from tg_repost.webui import auth, setup_token
from tg_repost.webui.app import create_app

# F28: страницы стоп-слов/доменов/доверенных требуют хотя бы одну цель с
# use_guardian=True (TargetGroup, tg_repost-БД) — совпадает с GUARDIAN_GROUP_ID
# из tests/conftest.py только по совпадению исторического значения, реальная
# связь теперь идёт ИСКЛЮЧИТЕЛЬНО через галочку на цели, не через .env.
_CHAT_ID = -100123


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Тот же паттерн изоляции, что и `test_app_routes.py` (см. его
    docstring про причины каждого шага), плюс очистка таблиц Guardian —
    отдельная БД, но тоже общий engine-синглтон на весь pytest-процесс."""
    monkeypatch.chdir(tmp_path)
    with session_scope() as session:
        session.query(AdminUser).delete()
        session.query(AppSetting).delete()
        session.query(Secret).delete()
        session.query(Source).delete()
        session.query(TelethonSession).delete()
        session.query(TargetGroup).delete()
    with guardian_session_scope() as session:
        session.query(StopWord).delete()
        session.query(AllowedDomain).delete()
        session.query(BotConfig).delete()
        session.query(TrustedUser).delete()
        session.query(Member).delete()
        session.query(ModerationLog).delete()
    os.environ.pop("WEBUI_MASTER_KEY", None)
    os.environ.pop("WEBUI_SESSION_SECRET", None)
    setup_token._token = None
    auth._failed_attempts.clear()

    async def _noop_start_components(settings):
        del settings

    monkeypatch.setattr(app_module, "start_components", _noop_start_components)

    from tg_repost.config import invalidate_settings_cache

    invalidate_settings_cache()
    guardian_invalidate_cache()
    yield
    setup_token._token = None
    auth._failed_attempts.clear()
    invalidate_settings_cache()
    guardian_invalidate_cache()


def _client() -> TestClient:
    return TestClient(create_app())


def _bootstrap(client: TestClient, password: str = "smoke-test-password-123") -> None:
    token = setup_token.get_or_create_setup_token()
    r = client.post(
        f"/setup?token={token}",
        data={"password": password, "password_confirm": password},
        follow_redirects=False,
    )
    assert r.status_code == 303, (r.status_code, r.text[:500])


def _add_guardian_target(chat_id: int = _CHAT_ID, title: str = "Test Group") -> None:
    """F28: страницы стоп-слов/доменов/доверенных требуют выбранную группу —
    без хотя бы одной цели с `use_guardian=True` селектор пуст."""
    with session_scope() as session:
        session.add(
            TargetGroup(chat_id=chat_id, title=title, is_active=True, use_guardian=True)
        )


def test_guardian_dashboard_requires_login():
    client = _client()
    r = client.get("/guardian", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_guardian_dashboard_loads_after_login():
    client = _client()
    _bootstrap(client)
    r = client.get("/guardian")
    assert r.status_code == 200


def test_guardian_settings_round_trip():
    client = _client()
    _bootstrap(client)
    r = client.post(
        "/guardian/settings/spam_filter",
        data={"spam_mode": "hybrid", "ai_spam_confidence_threshold": "0.65"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    from guardian.config import get_guardian_settings

    settings = get_guardian_settings()
    assert settings.spam_mode == "hybrid"
    assert settings.ai_spam_confidence_threshold == pytest.approx(0.65)


def test_guardian_settings_invalid_number_returns_clean_400():
    client = _client()
    _bootstrap(client)
    r = client.post(
        "/guardian/settings/warns",
        data={"warn_threshold_mute": "not-a-number"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "число" in r.text.lower()


def test_guardian_settings_rejects_invalid_spam_mode_choice():
    """Регрессия на код-ревью: spam_mode раньше принимал любую строку —
    опечатка вида "hybird" молча проходила бы валидацию и спам-фильтр тихо
    переставал бы работать (messages.py сверяет с конкретными строками)."""
    client = _client()
    _bootstrap(client)
    r = client.post(
        "/guardian/settings/spam_filter",
        data={"spam_mode": "hybird", "ai_spam_confidence_threshold": "0.8"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "keywords" in r.text

    from guardian.config import get_guardian_settings

    assert get_guardian_settings().spam_mode == "keywords"  # не изменилось


def test_guardian_trusted_add_blocked_when_chat_not_protected():
    """F28: ни одна цель не отмечена галочкой Guardian — форма шлёт
    chat_id, которого нет среди защищаемых, `_validate_chat_id` отклоняет."""
    client = _client()
    _bootstrap(client)
    r = client.post(
        "/guardian/trusted",
        data={"user_id": "111222333", "chat_id": str(_CHAT_ID)},
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_guardian_stopwords_add_list_delete_round_trip():
    client = _client()
    _bootstrap(client)
    _add_guardian_target()

    r = client.post(
        "/guardian/stopwords",
        data={"word": "КАЗИНО", "chat_id": str(_CHAT_ID)},
        follow_redirects=False,
    )
    assert r.status_code == 303
    r = client.get("/guardian/stopwords")
    assert "казино" in r.text

    r = client.post(
        "/guardian/stopwords/delete",
        data={"word": "казино", "chat_id": str(_CHAT_ID)},
        follow_redirects=False,
    )
    assert r.status_code == 303
    r = client.get("/guardian/stopwords")
    assert "казино" not in r.text


def test_guardian_domains_add_normalizes_and_deletes():
    # Домен намеренно не пересекается с placeholder'ом формы ("example.com")
    # в шаблоне — иначе "удалили, но placeholder всё ещё на странице" дал бы
    # ложноположительный "not in r.text".
    client = _client()
    _bootstrap(client)
    _add_guardian_target()

    r = client.post(
        "/guardian/domains",
        data={"domain": "WWW.Guardiantest.ORG", "chat_id": str(_CHAT_ID)},
        follow_redirects=False,
    )
    assert r.status_code == 303

    from guardian import domains_repo

    assert domains_repo.list_allowed_domains(_CHAT_ID) == ["guardiantest.org"]
    r = client.get("/guardian/domains")
    assert "guardiantest.org" in r.text

    r = client.post(
        "/guardian/domains/delete",
        data={"domain": "guardiantest.org", "chat_id": str(_CHAT_ID)},
        follow_redirects=False,
    )
    r = client.get("/guardian/domains")
    assert "guardiantest.org" not in r.text


def test_guardian_trusted_add_and_delete_round_trip():
    # user_id намеренно не пересекается с placeholder'ом формы ("123456789").
    client = _client()
    _bootstrap(client)
    _add_guardian_target()

    r = client.post(
        "/guardian/trusted",
        data={"user_id": "555444333", "chat_id": str(_CHAT_ID), "reason": "friend"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    r = client.get("/guardian/trusted")
    assert "555444333" in r.text

    r = client.post(
        f"/guardian/trusted/555444333/delete?chat_id={_CHAT_ID}",
        follow_redirects=False,
    )
    assert r.status_code == 303
    r = client.get("/guardian/trusted")
    assert "555444333" not in r.text


def test_guardian_trusted_rejects_non_numeric_user_id():
    client = _client()
    _bootstrap(client)
    _add_guardian_target()
    r = client.post(
        "/guardian/trusted",
        data={"user_id": "not-a-number", "chat_id": str(_CHAT_ID)},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "число" in r.text.lower()


def test_guardian_mutations_write_audit_log():
    client = _client()
    _bootstrap(client)
    _add_guardian_target()
    client.post(
        "/guardian/stopwords",
        data={"word": "спамслово", "chat_id": str(_CHAT_ID)},
        follow_redirects=False,
    )
    r = client.get("/audit")
    # Сырой action-ключ гуманизируется в UI (аудит: "guardian_stopword_add"
    # нечитаем для не-разработчика) — см. i18n.humanize_action / audit.html.
    assert "Добавлено стоп-слово" in r.text
    assert "спамслово" in r.text
