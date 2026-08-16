"""Чеклист первых шагов на главной (юзабилити, 2026-08-16).

До этого на главной висело одно предупреждение «система не настроена» —
верное и бесполезное: не говорило ни что именно не задано, ни куда идти.
Владелец сформулировал результат так: «зашёл в админку, ничего не понятно».

Главное свойство чеклиста — он ВЫЧИСЛЯЕТСЯ. Список, написанный руками,
разойдётся с системой на первой же фиче и начнёт врать, а врущий чеклист
хуже отсутствующего: по нему всё сделано, а ничего не работает. Поэтому
тесты проверяют, что шаги реагируют на реальное состояние.
"""

from __future__ import annotations

import pytest

from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401
from tg_repost.db.models import Secret, Source, TargetGroup
from tg_repost.db.session import session_scope
from tg_repost.webui import onboarding


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(Source).delete()
            session.query(TargetGroup).delete()

    _wipe()
    yield
    _wipe()


def _step(key: str):
    return next(s for s in onboarding.steps() if s.key == key)


# --- шаги отражают реальное состояние ---


def test_source_step_reacts_to_a_real_source():
    assert _step("sources").done is False

    with session_scope() as session:
        session.add(Source(channel_username="@test", channel_title="Тест"))

    assert _step("sources").done is True


def test_target_step_ignores_disabled_groups():
    """Выключенная цель публиковать не даст — считать её настроенной значит
    соврать."""
    with session_scope() as session:
        session.add(TargetGroup(chat_id=-100500, title="Выключенная", is_active=False))

    assert _step("targets").done is False

    with session_scope() as session:
        session.add(TargetGroup(chat_id=-100501, title="Рабочая", is_active=True))

    assert _step("targets").done is True


def test_secret_step_reacts_to_a_stored_secret():
    assert _step("bot_token").done is False

    with session_scope() as session:
        session.add(Secret(
            key="tg_bot_token", encrypted_value="зашифровано", masked_hint="••••ab12",
        ))

    assert _step("bot_token").done is True


def test_empty_secret_does_not_count():
    """Пустая строка в базе — это «поле трогали и стёрли», а не «задано»."""
    with session_scope() as session:
        session.add(Secret(
            key="tg_bot_token", encrypted_value="", masked_hint="",
        ))

    assert _step("bot_token").done is False


# --- сводка ---


def test_next_step_is_the_first_unfinished_required_one():
    """Человеку нужно знать, что делать СЕЙЧАС, а не сколько всего осталось.

    Проверяется именно ПОРЯДОК: до подсказанного шага не должно остаться ни
    одного невыполненного обязательного, иначе человека отправляют вперёд
    через пропущенную зависимость.
    """
    summary = onboarding.summary()
    required = [s for s in onboarding.steps() if s.required]

    assert summary["next_step"] is not None, "в тестовом окружении всё настроено?"
    position = [s.key for s in required].index(summary["next_step"].key)
    assert all(s.done for s in required[:position])
    assert not summary["next_step"].done


def test_optional_steps_do_not_block_readiness():
    """Guardian и Engage — отдельные боты; ядро работает без них целиком.

    Иначе человека заставляли бы завести трёх ботов, чтобы опубликовать один
    пост.
    """
    optional = [s for s in onboarding.steps() if not s.required]

    assert {s.key for s in optional} == {"guardian", "engage"}
    assert all(not s.done for s in optional)
    assert onboarding.summary()["total_count"] == len(
        [s for s in onboarding.steps() if s.required]
    )


def test_key_list_matches_the_real_steps():
    """`STEP_KEYS` существует ради проверки переводов без базы — и обязан
    совпадать с настоящим набором, иначе он охраняет не то."""
    assert [s.key for s in onboarding.steps()] == list(onboarding.STEP_KEYS)


def test_every_step_has_a_page_to_go_to():
    """Шаг без адреса — совет без действия."""
    from tg_repost.webui.app import create_app

    paths = set(create_app().openapi()["paths"])

    for step in onboarding.steps():
        assert step.href in paths, step.key


def test_every_step_is_explained_in_both_languages():
    """Название шага без объяснения «зачем» — это то же самое непонятно,
    только пунктом ниже."""
    from tg_repost.webui.i18n import STRINGS, SUPPORTED_LANGS

    for step in onboarding.steps():
        for prefix in ("onboarding.step.", "onboarding.why."):
            key = prefix + step.key
            assert key in STRINGS, key
            for lang in SUPPORTED_LANGS:
                assert STRINGS[key].get(lang), f"{key}.{lang}"


# --- на странице ---


def test_dashboard_shows_the_checklist_when_not_ready():
    client = _client()
    _bootstrap(client)

    body = client.get("/").text

    assert "Первые шаги" in body
    assert "Хотя бы один источник" in body


def test_checklist_links_to_where_the_work_is_done():
    client = _client()
    _bootstrap(client)

    body = client.get("/").text

    assert 'href="/sources"' in body
    assert 'href="/targets"' in body


def test_checklist_disappears_when_everything_is_ready(monkeypatch):
    """Постоянная памятка о сделанном только занимает место."""
    monkeypatch.setattr(
        onboarding, "summary",
        lambda: {"steps": [], "done_count": 7, "total_count": 7,
                 "is_ready": True, "next_step": None},
    )
    client = _client()
    _bootstrap(client)

    body = client.get("/").text

    assert "Первые шаги" not in body
