"""Тесты шифрования секретов at rest (F23, Фаза 5.1)."""

import pytest
from cryptography.fernet import InvalidToken

from tg_repost.crypto import append_env_var, decrypt, encrypt, generate_key, mask


def test_encrypt_decrypt_round_trip():
    key = generate_key()
    token = encrypt("sk-super-secret-value", key)
    assert decrypt(token, key) == "sk-super-secret-value"


def test_encrypted_value_differs_from_plaintext():
    key = generate_key()
    token = encrypt("plaintext-here", key)
    assert token != "plaintext-here"


def test_decrypt_with_wrong_key_raises():
    key_a = generate_key()
    key_b = generate_key()
    token = encrypt("secret", key_a)
    with pytest.raises(InvalidToken):
        decrypt(token, key_b)


def test_generate_key_produces_usable_fernet_key():
    key = generate_key()
    # Должен быть пригоден для немедленного шифрования без ошибок формата.
    token = encrypt("x", key)
    assert decrypt(token, key) == "x"


def test_generate_key_is_unique_each_call():
    assert generate_key() != generate_key()


def test_mask_short_value_fully_hidden():
    assert mask("ab") == "••••"
    assert mask("abcd") == "••••"


def test_mask_long_value_shows_last_four():
    assert mask("sk-1234567890abcd") == "••••abcd"


def test_mask_never_contains_full_secret():
    secret = "sk-realsecretvalue123"
    masked = mask(secret)
    assert secret not in masked
    assert masked.endswith(secret[-4:])


def test_append_env_var_creates_file(tmp_path):
    env_path = tmp_path / ".env"
    append_env_var("FOO", "bar", env_path=str(env_path))
    assert env_path.read_text(encoding="utf-8") == "FOO=bar\n"


def test_append_env_var_appends_to_existing_without_trailing_newline(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("EXISTING=1", encoding="utf-8")
    append_env_var("NEW_VAR", "value", env_path=str(env_path))
    content = env_path.read_text(encoding="utf-8")
    assert content == "EXISTING=1\nNEW_VAR=value\n"


def test_append_env_var_appends_to_existing_with_trailing_newline(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("EXISTING=1\n", encoding="utf-8")
    append_env_var("NEW_VAR", "value", env_path=str(env_path))
    content = env_path.read_text(encoding="utf-8")
    assert content == "EXISTING=1\nNEW_VAR=value\n"
