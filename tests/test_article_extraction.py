"""Извлечение тела статьи: trafilatura как основной путь, BS4 — запасной.

Жалоба «инфу не добирает»: голая BS4-эвристика на сложной вёрстке тянула
меню/футеры или возвращала пусто, рерайт шёл по обрывкам, модель добирала
выдумками. trafilatura отбрасывает обвязку и оставляет собственно текст.

Всё оффлайн: `extract_article_text` — чистая функция над HTML, без сети.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from tg_repost.enrichment.link_content import (
    _extract_main_text,
    _extract_with_trafilatura,
    extract_article_text,
)

_ARTICLE_HTML = """<html><head><title>Заголовок</title></head><body>
<nav>Главная О нас Подписаться Реклама Контакты</nav>
<aside>Читайте также: десять других статей со ссылками на подписку</aside>
<article>
  <h1>Новая уязвимость в популярной библиотеке</h1>
  <p>Исследователи обнаружили серьёзную проблему в широко используемом
     компоненте, которая позволяет удалённое выполнение кода при определённых
     условиях конфигурации сервера.</p>
  <p>По словам авторов отчёта, уязвимость затрагивает версии с 2.0 по 2.8 и
     уже устранена в свежем релизе. Администраторам рекомендуется обновиться.</p>
  <p>Эксплуатация требует, чтобы злоумышленник имел доступ к внутреннему
     API, что снижает практический риск, но не отменяет необходимости патча.</p>
</article>
<footer>Copyright 2026. Подпишитесь на рассылку. Все права защищены.</footer>
</body></html>"""


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def test_trafilatura_keeps_article_drops_chrome():
    text = extract_article_text(_ARTICLE_HTML, _soup(_ARTICLE_HTML), max_chars=5000)
    # тело статьи на месте
    assert "удалённое выполнение кода" in text
    assert "версии с 2.0 по 2.8" in text
    # меню/футер/«читайте также» — выброшены
    assert "Подписаться" not in text
    assert "Все права защищены" not in text
    assert "Читайте также" not in text


def test_falls_back_to_bs4_when_trafilatura_finds_nothing():
    """На вырожденной странице (нет тела статьи в понимании trafilatura)
    экстрактор откатывается на BS4, а не возвращает пусто на ровном месте."""
    # див с длинным текстом, без <article>/<p> — trafilatura часто ничего не
    # извлекает, а BS4-эвристика берёт текст контейнера.
    html = "<html><body><div>" + ("живой осмысленный текст статьи " * 20) + "</div></body></html>"
    got = extract_article_text(html, _soup(html), max_chars=5000)
    assert "осмысленный текст статьи" in got


def test_max_chars_is_respected():
    long_html = (
        "<html><body><article>"
        + "".join(f"<p>{'абзац номер такой-то с достаточной длиной ' * 3}</p>" for _ in range(50))
        + "</article></body></html>"
    )
    got = extract_article_text(long_html, _soup(long_html), max_chars=300)
    assert len(got) <= 300


def test_trafilatura_helper_returns_empty_on_junk():
    """Пустой/мусорный HTML — пустая строка, чтобы сработал откат на BS4."""
    assert _extract_with_trafilatura("") == ""
    assert _extract_with_trafilatura("<html></html>") == ""


def test_bs4_fallback_still_works_standalone():
    """Запасной путь не сломан — прежняя эвристика на месте."""
    text = _extract_main_text(_soup(_ARTICLE_HTML), max_chars=5000)
    assert "удалённое выполнение кода" in text
