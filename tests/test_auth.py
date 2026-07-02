"""Тесты аутентификации веб-админки (F23, Фаза 5.1; Фаза 5-аудит: таймауты
сессии и rate-limit на /login)."""

import time

import pytest

from tg_repost.db.models import AdminUser
from tg_repost.db.session import session_scope
from tg_repost.webui import auth
from tg_repost.webui.auth import (
    NotAuthenticatedError,
    clear_failed_logins,
    create_admin,
    hash_password,
    is_bootstrapped,
    is_login_locked,
    log_in,
    register_failed_login,
    require_login,
    verify_login,
    verify_password,
)


class _FakeRequest:
    """Минимальная замена `starlette.Request` для юнит-тестов `auth.py` —
    `log_in`/`log_out`/`require_login` трогают только `request.session`
    (dict-подобный объект), полноценный Starlette Request не нужен."""

    def __init__(self, session: dict | None = None):
        self.session: dict = session if session is not None else {}


@pytest.fixture(autouse=True)
def _clear_failed_attempts():
    """Изоляция: `_failed_attempts` — модульный синглтон."""
    auth._failed_attempts.clear()
    yield
    auth._failed_attempts.clear()


def _clear_admin_users() -> None:
    with session_scope() as session:
        session.query(AdminUser).delete()


def test_hash_password_round_trip():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed) is True


def test_hash_password_rejects_wrong_password():
    hashed = hash_password("right-password")
    assert verify_password("wrong-password", hashed) is False


def test_hash_password_not_plaintext():
    hashed = hash_password("my-password")
    assert hashed != "my-password"
    assert "my-password" not in hashed


def test_is_bootstrapped_false_when_no_admin():
    _clear_admin_users()
    assert is_bootstrapped() is False


def test_create_admin_then_bootstrapped_true():
    _clear_admin_users()
    create_admin("supersecretpw123")
    assert is_bootstrapped() is True


def test_create_admin_twice_raises():
    _clear_admin_users()
    create_admin("first-password")
    with pytest.raises(RuntimeError):
        create_admin("second-password")


def test_verify_login_correct_password():
    _clear_admin_users()
    create_admin("the-real-password")
    assert verify_login("the-real-password") is True


def test_verify_login_wrong_password():
    _clear_admin_users()
    create_admin("the-real-password")
    assert verify_login("not-the-password") is False


def test_verify_login_false_when_no_admin():
    _clear_admin_users()
    assert verify_login("anything") is False


def test_log_in_sets_session_keys_and_require_login_passes():
    request = _FakeRequest()
    log_in(request)
    assert request.session["logged_in"] is True
    require_login(request)  # не должно бросить


def test_require_login_raises_without_session():
    request = _FakeRequest()
    with pytest.raises(NotAuthenticatedError):
        require_login(request)


def test_require_login_raises_for_legacy_session_without_timestamps():
    """Регрессия: раньше сессия проверялась только по флагу `logged_in`,
    без временных меток — найдено при security-аудите Фазы 5. Сессия,
    созданная до этого фикса (нет login_at/last_seen), должна считаться
    истёкшей, а не бессрочно валидной."""
    request = _FakeRequest({"logged_in": True})
    with pytest.raises(NotAuthenticatedError):
        require_login(request)


def test_require_login_raises_after_idle_timeout():
    request = _FakeRequest()
    log_in(request)
    request.session["last_seen"] = time.time() - auth._IDLE_TIMEOUT_SECONDS - 1
    with pytest.raises(NotAuthenticatedError):
        require_login(request)


def test_require_login_raises_after_absolute_timeout():
    request = _FakeRequest()
    log_in(request)
    old = time.time() - auth._ABSOLUTE_TIMEOUT_SECONDS - 1
    request.session["login_at"] = old
    request.session["last_seen"] = old
    with pytest.raises(NotAuthenticatedError):
        require_login(request)


def test_require_login_refreshes_last_seen():
    request = _FakeRequest()
    log_in(request)
    stale = time.time() - 100
    request.session["last_seen"] = stale
    require_login(request)
    assert request.session["last_seen"] > stale


def test_is_login_locked_false_initially():
    assert is_login_locked("1.2.3.4") is False


def test_is_login_locked_true_after_max_attempts():
    for _ in range(5):
        register_failed_login("1.2.3.4")
    assert is_login_locked("1.2.3.4") is True


def test_is_login_locked_false_below_threshold():
    for _ in range(4):
        register_failed_login("1.2.3.4")
    assert is_login_locked("1.2.3.4") is False


def test_is_login_locked_expires_after_window():
    for _ in range(5):
        register_failed_login("1.2.3.4")
    assert is_login_locked("1.2.3.4") is True
    # Состарить попытки искусственно, вместо реального sleep на 30с.
    auth._failed_attempts["1.2.3.4"] = [
        t - auth._LOGIN_LOCKOUT_SECONDS - 1 for t in auth._failed_attempts["1.2.3.4"]
    ]
    assert is_login_locked("1.2.3.4") is False


def test_is_login_locked_prunes_empty_entry_from_dict():
    # Регрессия (security-ревью): раньше пустой список ПОСЛЕ прунинга
    # оставался в словаре навсегда (только .get() выше, без .pop()) — ключи
    # для IP с одной устаревшей попыткой копились бы бесконечно на весь
    # процесс. Низкий приоритет (loopback-only периметр), но дёшево починить.
    register_failed_login("1.2.3.4")
    auth._failed_attempts["1.2.3.4"] = [
        t - auth._LOGIN_LOCKOUT_SECONDS - 1 for t in auth._failed_attempts["1.2.3.4"]
    ]
    assert is_login_locked("1.2.3.4") is False
    assert "1.2.3.4" not in auth._failed_attempts


def test_clear_failed_logins_resets_counter():
    for _ in range(5):
        register_failed_login("1.2.3.4")
    clear_failed_logins("1.2.3.4")
    assert is_login_locked("1.2.3.4") is False


def test_is_login_locked_isolated_per_client():
    for _ in range(5):
        register_failed_login("1.2.3.4")
    assert is_login_locked("5.6.7.8") is False
