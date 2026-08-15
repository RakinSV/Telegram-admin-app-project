"""Маркировка рекламы в админке (F62).

Блок маркировки появляется на `/ads` только когда она включена — иначе на
странице висели бы три пустых поля без объяснения, зачем они. Отдельный
файл, потому что общий тест переводов проходит страницы при настройках по
умолчанию, то есть с ВЫКЛЮЧЕННОЙ маркировкой и этого блока не видит.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401
from tg_repost import ad_marking
from tg_repost.ads import repo as ads_repo
from tg_repost.db.models import AdBrief, Post, PostTarget
from tg_repost.db.session import session_scope

ADVERTISER = "ООО «Ромашка»"
ERID = "2Vfnxabcdef"


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(PostTarget).delete()
            session.query(Post).delete()
            session.query(AdBrief).delete()

    _wipe()
    yield
    _wipe()


@pytest.fixture
def _marking_on(monkeypatch):
    from tg_repost import config

    real = config.get_settings()
    monkeypatch.setattr(
        "tg_repost.webui.crud_routes.get_settings",
        lambda: SimpleNamespace(**{**real.model_dump(), "ad_marking_enabled": True}),
    )


def test_marking_fields_hidden_while_disabled():
    client = _client()
    _bootstrap(client)
    ads_repo.add_brief("Купите ромашки")

    assert "erid" not in client.get("/ads").text


def test_marking_fields_shown_when_enabled(_marking_on):
    client = _client()
    _bootstrap(client)
    ads_repo.add_brief("Купите ромашки")

    response = client.get("/ads")

    assert "erid" in response.text
    assert "/marking" in response.text


def test_marking_is_saved_through_the_form(_marking_on):
    client = _client()
    _bootstrap(client)
    brief = ads_repo.add_brief("Купите ромашки")

    response = client.post(
        f"/ads/{brief.id}/marking",
        data={"advertiser_legal_name": ADVERTISER, "advertiser_inn": "7701234567",
              "erid": ERID},
        follow_redirects=False,
    )

    assert response.status_code == 303
    marking = ad_marking.marking_of(brief.id)
    assert marking is not None and marking.is_complete


def test_brief_without_erid_is_flagged_on_the_page(_marking_on):
    """Без пометки «нет erid» бриф выглядит готовым к публикации."""
    client = _client()
    _bootstrap(client)
    ads_repo.add_brief("Купите ромашки")

    assert "нет erid" in client.get("/ads").text


def test_marking_form_on_missing_brief_does_not_crash(_marking_on):
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/ads/999999/marking",
        data={"advertiser_legal_name": ADVERTISER, "advertiser_inn": "", "erid": ERID},
        follow_redirects=False,
    )

    assert response.status_code == 303


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_no_missing_translations_with_marking_on(_marking_on, lang):
    client = _client()
    _bootstrap(client)
    ads_repo.add_brief("Купите ромашки")

    client.get(f"/lang/{lang}?next=/ads", follow_redirects=False)
    response = client.get("/ads")

    assert not re.compile(r"\[[a-z_]+\.[a-z_]+\]").findall(response.text)
