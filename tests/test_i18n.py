"""Тесты слоя i18n (RU/EN) веб-админки — каталог строк (`webui/i18n.py`),
переключатель языка (`/lang/{code}`), и сквозной смоук-тест «ни одна
страница не показывает необработанный ключ перевода» на обоих языках.

Последнее — самый ценный тест здесь: каталог строк вырос до ~450 записей
за один проход, ручная проверка каждой страницы на обоих языках
нереалистична — а забытый/опечатанный ключ иначе тихо показал бы
пользователю `[some.key]` вместо текста."""

from __future__ import annotations

import os
import re

import pytest
from fastapi.testclient import TestClient

from tg_repost.db.models import AdminUser, AppSetting, Secret, Source
from tg_repost.db.session import session_scope
from tg_repost.webui import app as app_module
from tg_repost.webui import auth, i18n, setup_token
from tg_repost.webui.app import create_app

_MISSING_KEY_RE = re.compile(r"\[[a-z_]+(?:\.[a-z_0-9]+)+\]")


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """См. аналогичную фикстуру в test_app_routes.py — тот же паттерн
    изоляции (CWD/БД/модульные синглтоны), не дублируется описание."""
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
    i18n.set_current_lang(i18n.DEFAULT_LANG)


def _client() -> TestClient:
    return TestClient(create_app())


def _bootstrap(client: TestClient, password: str = "i18n-test-password-1") -> None:
    token = setup_token.get_or_create_setup_token()
    r = client.post(
        f"/setup?token={token}",
        data={"password": password, "password_confirm": password},
        follow_redirects=False,
    )
    assert r.status_code == 303, (r.status_code, r.text[:500])
    r = client.post("/login", data={"password": password}, follow_redirects=False)
    assert r.status_code == 303, (r.status_code, r.text[:500])


def test_every_catalog_entry_has_both_languages():
    missing = [
        key for key, entry in i18n.STRINGS.items()
        if "ru" not in entry or "en" not in entry
    ]
    assert missing == []


def test_t_returns_bracketed_key_for_missing_translation():
    assert i18n.t("totally.made.up.key.that.does.not.exist") == "[totally.made.up.key.that.does.not.exist]"


def test_t_falls_back_to_default_lang_if_current_lang_entry_missing():
    i18n.STRINGS["_test_partial_key"] = {"ru": "только русский"}
    try:
        i18n.set_current_lang("en")
        assert i18n.t("_test_partial_key") == "только русский"
    finally:
        del i18n.STRINGS["_test_partial_key"]
        i18n.set_current_lang(i18n.DEFAULT_LANG)


def test_t_applies_format_kwargs():
    i18n.set_current_lang("ru")
    assert i18n.t("common.list_truncated", limit=500) == (
        "Показаны первые 500 записей — уточните список, если их больше."
    )


def test_opt_returns_empty_string_for_missing_key():
    """`opt()` — для НЕОБЯЗАТЕЛЬНЫХ строк (подсказки к полям настроек): их
    около сотни, подсказка осмысленна далеко не у каждого поля, и `t()`
    вывалил бы в интерфейс "[settings.field.x.hint]" для всех остальных."""
    assert i18n.opt("нет.такого.ключа.вообще") == ""


def test_opt_returns_translation_when_key_exists():
    i18n.set_current_lang("ru")
    assert i18n.opt("settings.field.rewrite_temperature.hint").startswith("Насколько")


def test_opt_does_not_crash_on_format_kwargs_for_missing_key():
    # Пустая строка не должна пытаться .format() и падать на KeyError.
    assert i18n.opt("нет.такого.ключа", limit=5) == ""


def test_humanize_action_known_and_unknown():
    i18n.set_current_lang("ru")
    assert i18n.humanize_action("source_add") == "Добавлен источник"
    # Неизвестный/будущий action — не ломается, просто отдаёт сырой ключ
    # (runtime-значение из БД, а не забытый ключ каталога — см. docstring).
    assert i18n.humanize_action("some_future_action") == "some_future_action"


def test_confirm_strings_contain_no_apostrophes():
    """Регрессионный гвард (см. комментарий-предупреждение в i18n.py над
    common.confirm_delete): строки confirm_* подставляются в JS confirm()
    внутри HTML-атрибута onsubmit — апостроф в тексте ломает JS-строку,
    т.к. Jinja HTML-экранирование не эквивалентно JS-экранированию."""
    for key, entry in i18n.STRINGS.items():
        if not key.startswith("common.confirm_") and "confirm" not in key:
            continue
        for lang, text in entry.items():
            assert "'" not in text, f"{key}[{lang}] contains an apostrophe: {text!r}"


def test_lang_switch_sets_session_and_redirects():
    client = _client()
    _bootstrap(client)
    r = client.get("/lang/en?next=/sources", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/sources"
    r = client.get("/sources")
    assert "Sources" in r.text
    assert "Источники" not in r.text


def test_lang_switch_rejects_unknown_code_falls_back_to_default():
    client = _client()
    _bootstrap(client)
    client.get("/lang/fr?next=/sources", follow_redirects=False)
    r = client.get("/sources")
    assert "Источники" in r.text  # неизвестный код -> дефолтный ru, не падение


def test_lang_switch_rejects_open_redirect_via_next():
    client = _client()
    _bootstrap(client)
    r = client.get("/lang/en?next=https://evil.example.com/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"  # внешний next отклонён, редирект на "/"


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_no_unresolved_translation_keys_across_pages(lang):
    """Смоук: заходим на широкий набор авторизованных страниц на каждом
    языке и убеждаемся, что нигде не всплыл необработанный `[dotted.key]`
    (см. `i18n.t()` fallback) — ловит опечатки в ключах шаблонов и
    отсутствующие переводы разом, без ручной проверки каждой страницы."""
    client = _client()
    _bootstrap(client)
    client.get(f"/lang/{lang}", follow_redirects=False)

    paths = [
        "/", "/sources", "/targets", "/moderation", "/ads", "/polls",
        "/invites", "/export",
        "/telethon-sessions", "/stats", "/stats/best-times", "/stats/growth",
        "/components", "/settings", "/audit", "/logs",
        "/guardian", "/guardian/settings", "/guardian/stopwords",
        "/guardian/domains", "/guardian/trusted",
    ]
    for path in paths:
        r = client.get(path)
        assert r.status_code == 200, (path, r.status_code)
        found = _MISSING_KEY_RE.findall(r.text)
        assert not found, f"{path} ({lang}) has unresolved translation keys: {found}"


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_no_unresolved_translation_keys_on_moderation_detail_with_variants(lang):
    """`/moderation/{id}` не входит в общий смоук выше — ему нужен реальный
    post_id в URL, а не просто путь без параметров. Отдельный тест: пост с
    >1 вариантом текста и обложки (F06/F18-доп.) — рендерит секции
    "Варианты текста"/"Варианты обложки", которые не проверялись бы иначе."""
    from tg_repost.db.models import Post, PostCoverVariant, PostKind, PostRewriteVariant, PostStatus

    client = _client()
    _bootstrap(client)
    client.get(f"/lang/{lang}", follow_redirects=False)

    with session_scope() as session:
        post = Post(
            kind=PostKind.SOURCE, original_text="orig", rewritten_text="v0",
            status=PostStatus.PENDING_APPROVAL, active_rewrite_variant_index=0,
            active_cover_variant_index=0,
        )
        session.add(post)
        session.flush()
        post_id = post.id
        session.add(PostRewriteVariant(post_id=post_id, variant_index=0, text="v0", tokens=1))
        session.add(PostRewriteVariant(post_id=post_id, variant_index=1, text="v1", tokens=1))
        session.add(PostCoverVariant(post_id=post_id, variant_index=0, media_path="a.jpg"))
        session.add(PostCoverVariant(post_id=post_id, variant_index=1, media_path="b.jpg"))

    try:
        r = client.get(f"/moderation/{post_id}")
        assert r.status_code == 200
        found = _MISSING_KEY_RE.findall(r.text)
        assert not found, f"/moderation/{post_id} ({lang}) has unresolved translation keys: {found}"
    finally:
        # Без явной очистки PostRewriteVariant/PostCoverVariant переживают
        # удаление Post (нет ON DELETE CASCADE) — при полном опустошении
        # таблицы posts в другом тесте SQLite может переиспользовать этот же
        # id для НОВОГО поста, и осиротевшие варианты "всплывают" у него
        # (найдено на прогоне полного сьюта: ловил test_post_variants.py).
        with session_scope() as session:
            session.query(PostRewriteVariant).filter(PostRewriteVariant.post_id == post_id).delete()
            session.query(PostCoverVariant).filter(PostCoverVariant.post_id == post_id).delete()
            session.query(Post).filter(Post.id == post_id).delete()


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_no_unresolved_translation_keys_on_public_pages(lang):
    client = _client()
    client.get(f"/lang/{lang}", follow_redirects=False)
    r = client.get("/login")
    assert not _MISSING_KEY_RE.findall(r.text)

    token = setup_token.get_or_create_setup_token()
    r = client.get(f"/setup?token={token}")
    assert not _MISSING_KEY_RE.findall(r.text)
