"""Guardian берёт провайдера из админки репост-бота (найдено 2026-08-22).

ЧТО БЫЛО. У Guardian есть свои поля `openai_base_url`/`openai_api_key`/
`openai_model`, и в комментарии к ним написано «переиспользует те же ключи,
что и репост-бот». Так и задумывалось, но на деле он читал ТОЛЬКО `.env`, а
владелец настраивает провайдера в админке — туда Guardian не смотрел вовсе, и
его настроек не было ни на одной странице.

ЧЕМ ЭТО ГРОЗИЛО. Замер на стенде: в админке стоял OmniRoute, а Guardian видел
`https://api.openai.com/v1` с ПУСТЫМ ключом. При `spam_mode=ai` или `hybrid`
это не ошибка на экране, а тишина: вызов падает, срабатывает fail-open
(намеренный — лучше пропустить спам, чем заблокировать живого человека), и
спам идёт в группу как ни в чём не бывало. Одна строка в логе.

КАК СДЕЛАНО. Адрес и ключ — общие, из зашифрованной базы репост-бота; двух
одинаковых полей в двух админках нет, потому что их забывают
синхронизировать. Модель Guardian может задать свою: классификация спама
проще рерайта, и на ней разумна модель подешевле.
"""

from __future__ import annotations

import json

import pytest

from guardian.config import get_guardian_settings
from guardian.db.models import BotConfig
from guardian.db.session import session_scope as guardian_session
from tg_repost.crypto import encrypt
from tg_repost.db.models import AppSetting, Secret
from tg_repost.db.session import session_scope as repost_session

MASTER_KEY = "sJ7Q0X4vY3mZ9pL2kR8tN6wB1cD5fG0hJ4uA7sE2yI0="


@pytest.fixture
def clean_state(monkeypatch):
    """Пустые обе базы и заданный мастер-ключ."""
    monkeypatch.setenv("WEBUI_MASTER_KEY", MASTER_KEY)
    with repost_session() as session:
        session.query(AppSetting).delete()
        session.query(Secret).delete()
    with guardian_session() as session:
        session.query(BotConfig).delete()
    yield
    with repost_session() as session:
        session.query(AppSetting).delete()
        session.query(Secret).delete()
    with guardian_session() as session:
        session.query(BotConfig).delete()


def _set_repost_provider(base_url: str, model: str, api_key: str) -> None:
    """Настроить провайдера так, как это делает админка репост-бота."""
    with repost_session() as session:
        session.add(AppSetting(key="openai_base_url", value=json.dumps(base_url),
                               value_type="str"))
        session.add(AppSetting(key="openai_model", value=json.dumps(model),
                               value_type="str"))
        session.add(Secret(key="openai_api_key",
                           encrypted_value=encrypt(api_key, MASTER_KEY),
                           masked_hint="••••" + api_key[-4:]))


def test_guardian_follows_the_provider_set_in_the_admin_panel(clean_state):
    """ГЛАВНЫЙ СЛУЧАЙ: настроили OmniRoute в админке — Guardian идёт туда же."""
    _set_repost_provider("http://168.168.88.34:20128/v1", "auto/cheap", "ключ-омнироута")

    settings = get_guardian_settings()

    assert settings.openai_base_url == "http://168.168.88.34:20128/v1", (
        "Guardian снова смотрит мимо админки — его AI-фильтр будет молча "
        "пропускать спам"
    )
    assert settings.openai_api_key == "ключ-омнироута"
    assert settings.openai_model == "auto/cheap"


def test_guardian_can_pin_its_own_cheaper_model(clean_state):
    """Модель — единственное, что Guardian задаёт сам: классификация спама
    проще рерайта, и на ней разумна модель подешевле."""
    _set_repost_provider("http://омнироут/v1", "auto/smart", "общий-ключ")
    with guardian_session() as session:
        session.add(BotConfig(key="openai_model", value=json.dumps("auto/cheap"),
                              updated_by="test"))

    settings = get_guardian_settings()

    assert settings.openai_model == "auto/cheap", "пин своей модели не сработал"
    # Адрес и ключ при этом остаются общими — их Guardian не переопределяет.
    assert settings.openai_base_url == "http://омнироут/v1"
    assert settings.openai_api_key == "общий-ключ"


def test_empty_model_in_guardian_means_same_as_repost(clean_state):
    """Пустое поле — это «как у репост-бота», а не «пустая модель».

    Форма настроек отправляет ВСЕ поля группы, включая незаполненные, поэтому
    пустая строка попадает в базу сама собой. Если бы она перекрывала общее
    значение, включение спам-фильтра ломало бы его же.
    """
    _set_repost_provider("http://омнироут/v1", "auto/smart", "общий-ключ")
    with guardian_session() as session:
        session.add(BotConfig(key="openai_model", value=json.dumps(""),
                              updated_by="test"))

    settings = get_guardian_settings()

    assert settings.openai_model == "auto/smart", (
        "пустое поле модели затёрло общую настройку"
    )


def test_missing_repost_settings_do_not_break_guardian(clean_state):
    """Обратная проверка: пока провайдер не настроен, Guardian просто живёт на
    своих .env-значениях. Чтение чужой базы не должно его ронять."""
    settings = get_guardian_settings()

    assert settings.openai_base_url  # что-то есть, процесс жив
    assert settings.spam_mode in ("keywords", "ai", "hybrid")


def test_broken_master_key_falls_back_instead_of_crashing(clean_state, monkeypatch):
    """Битый ключ не должен ронять Guardian на чтении настроек — иначе бот
    не поднимется вовсе из-за одной испорченной строки в чужой базе."""
    _set_repost_provider("http://омнироут/v1", "auto/cheap", "ключ")
    monkeypatch.setenv("WEBUI_MASTER_KEY", "wrONGkeyWRongKEYwrongKEYwrongKEYwrongKEY0=")

    settings = get_guardian_settings()

    # Адрес всё равно виден (он не шифруется), а ключ откатился на .env.
    assert settings.openai_base_url == "http://омнироут/v1"
    assert settings.openai_api_key != "ключ"


def test_settings_page_shows_the_model_field():
    """Достижимость: поле должно быть на странице, иначе задать его нечем."""
    from guardian.settings_store import SETTINGS_GROUPS

    fields = {f.name for group in SETTINGS_GROUPS for f in group.fields}
    assert "openai_model" in fields, "поле модели Guardian никуда не выведено"
