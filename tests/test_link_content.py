"""Тесты перехода по ссылке из поста для «настоящего» рерайта (F16-доп.):
чистая логика извлечения URL, SSRF-фильтр хоста и разбор HTML — без
реальной сети (тот же принцип, что test_covers.py/test_enrichment.py)."""

import socket

from bs4 import BeautifulSoup

from tg_repost.enrichment.link_content import (
    _extract_image,
    _extract_main_text,
    _is_public_host,
    _is_safe_url,
    extract_first_url,
)


def test_extract_first_url_found():
    text = "Смотри подробности: https://example.com/news/1 — интересно"
    assert extract_first_url(text) == "https://example.com/news/1"


def test_extract_first_url_strips_trailing_punctuation():
    assert extract_first_url("Читай тут: https://example.com/a.") == "https://example.com/a"
    assert extract_first_url("(см. https://example.com/b)") == "https://example.com/b"


def test_extract_first_url_none_when_absent():
    assert extract_first_url("просто текст без ссылок") is None


def test_extract_first_url_empty_text():
    assert extract_first_url("") is None


def test_extract_first_url_ignores_non_http_scheme():
    assert extract_first_url("tg://resolve?domain=x") is None


def test_is_public_host_rejects_loopback(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda host, port: [(socket.AF_INET, None, None, "", ("127.0.0.1", 0))],
    )
    assert _is_public_host("localhost") is False


def test_is_public_host_rejects_private_range(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda host, port: [(socket.AF_INET, None, None, "", ("192.168.1.5", 0))],
    )
    assert _is_public_host("internal.local") is False


def test_is_public_host_rejects_link_local(monkeypatch):
    # 169.254.169.254 — типичный адрес cloud metadata endpoint (SSRF-цель №1).
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda host, port: [(socket.AF_INET, None, None, "", ("169.254.169.254", 0))],
    )
    assert _is_public_host("metadata.internal") is False


def test_is_public_host_accepts_public_ip(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda host, port: [(socket.AF_INET, None, None, "", ("93.184.216.34", 0))],
    )
    assert _is_public_host("example.com") is True


def test_is_public_host_rejects_if_any_resolved_ip_is_private(monkeypatch):
    # Один публичный + один приватный адрес — отклоняем целиком (осторожный
    # выбор при multi-A DNS-ответе).
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda host, port: [
            (socket.AF_INET, None, None, "", ("93.184.216.34", 0)),
            (socket.AF_INET, None, None, "", ("10.0.0.1", 0)),
        ],
    )
    assert _is_public_host("mixed.example.com") is False


def test_is_public_host_false_on_dns_failure(monkeypatch):
    def _raise(host, port):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", _raise)
    assert _is_public_host("does-not-resolve.invalid") is False


def test_is_safe_url_rejects_non_http_scheme():
    assert _is_safe_url("ftp://example.com/a") is False
    assert _is_safe_url("file:///etc/passwd") is False


def test_is_safe_url_rejects_url_without_host():
    assert _is_safe_url("https://") is False


def test_is_safe_url_accepts_public_https(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda host, port: [(socket.AF_INET, None, None, "", ("93.184.216.34", 0))],
    )
    assert _is_safe_url("https://example.com/article") is True


def test_extract_main_text_prefers_article_tag():
    html = """
    <html><body>
      <nav>Меню сайта, не текст статьи</nav>
      <article>
        <p>Первый содержательный абзац статьи, длиннее сорока символов точно.</p>
        <p>Короткий.</p>
        <p>Второй содержательный абзац с деталями и цифрами по теме новости.</p>
      </article>
      <footer>Подвал сайта</footer>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    text = _extract_main_text(soup, max_chars=10_000)
    assert "Первый содержательный абзац" in text
    assert "Второй содержательный абзац" in text
    assert "Меню сайта" not in text
    assert "Подвал сайта" not in text
    assert "Короткий." not in text  # короче порога — отфильтрован как шум


def test_extract_main_text_truncates_to_max_chars():
    html = "<article><p>" + ("а" * 40 + " ") * 200 + "</p></article>"
    soup = BeautifulSoup(html, "html.parser")
    text = _extract_main_text(soup, max_chars=100)
    assert len(text) == 100


def test_extract_main_text_falls_back_to_body_text_without_paragraphs():
    soup = BeautifulSoup("<html><body>Просто голый текст без тегов p</body></html>", "html.parser")
    text = _extract_main_text(soup, max_chars=1000)
    assert "голый текст" in text


def test_extract_image_prefers_og_image():
    html = """
    <html><head>
      <meta property="og:image" content="/covers/main.jpg">
    </head><body><img src="/other.jpg"></body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    assert _extract_image(soup, "https://example.com/news/1") == "https://example.com/covers/main.jpg"


def test_extract_image_falls_back_to_first_img():
    soup = BeautifulSoup('<html><body><img src="pic.png"></body></html>', "html.parser")
    assert _extract_image(soup, "https://example.com/dir/") == "https://example.com/dir/pic.png"


def test_extract_image_none_when_absent():
    soup = BeautifulSoup("<html><body><p>нет картинок</p></body></html>", "html.parser")
    assert _extract_image(soup, "https://example.com/") is None


async def test_fetch_link_content_returns_none_for_unsafe_url():
    from tg_repost.enrichment.link_content import fetch_link_content

    assert await fetch_link_content("ftp://example.com/x") is None


async def test_download_link_image_returns_none_for_unsafe_url():
    from tg_repost.enrichment.link_content import download_link_image

    assert await download_link_image("http://127.0.0.1/x.jpg") is None
