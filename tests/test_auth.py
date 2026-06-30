"""Тесты аутентификации веб-админки (F23, Фаза 5.1)."""

import pytest

from tg_repost.db.models import AdminUser
from tg_repost.db.session import session_scope
from tg_repost.webui.auth import (
    create_admin,
    hash_password,
    is_bootstrapped,
    verify_login,
    verify_password,
)


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
