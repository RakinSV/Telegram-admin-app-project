"""Тесты sanitize_proxy_error (F10, security-ревью MTProto/SOCKS5-фичи) —
логин:пароль из URL прокси не должны попадать в логи/БД через str(exc)."""

from __future__ import annotations

from tg_repost.logging_conf import sanitize_proxy_error


def test_sanitize_proxy_error_strips_credentials_from_url():
    text = "ProxyError: connect to socks5://baduser:badpass@1.2.3.4:1080 failed"
    result = sanitize_proxy_error(text)
    assert "baduser" not in result
    assert "badpass" not in result
    assert "socks5://***:***@1.2.3.4:1080" in result


def test_sanitize_proxy_error_leaves_plain_text_untouched():
    text = "Connection timed out after 15 seconds"
    assert sanitize_proxy_error(text) == text


def test_sanitize_proxy_error_leaves_url_without_credentials_untouched():
    text = "Failed to reach https://api.telegram.org/bot123/sendMessage"
    assert sanitize_proxy_error(text) == text


def test_sanitize_proxy_error_handles_multiple_urls():
    text = "tried socks5://u1:p1@host1:1080 then socks5://u2:p2@host2:1080"
    result = sanitize_proxy_error(text)
    assert "u1" not in result and "p1" not in result
    assert "u2" not in result and "p2" not in result
    assert result.count("***:***@") == 2
