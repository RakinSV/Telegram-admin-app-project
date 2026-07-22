"""Страховки от рассинхрона «код ↔ админка», найденного на полном аудите.

Все эти проверки — про то, что добавили новое поле/секрет в код и забыли
показать его владельцу. Каждая ловит класс ошибки, который иначе замечается
только глазами на живом стенде.
"""

from __future__ import annotations

import re

from tg_repost.config import SECRET_FIELD_NAMES, Settings
from tg_repost.webui.i18n import STRINGS
from tg_repost.webui.settings_store import SECRET_HINTS, SECRET_LABELS, SETTINGS_GROUPS

# Править из админки эти поля нельзя по замыслу: бутстрап-ключи шифрования
# (иначе владелец способен одним сохранением сделать секреты нечитаемыми),
# пути к БД/логам/медиа (меняются только вместе с перезапуском процесса).
_DELIBERATELY_NOT_IN_UI = {
    "webui_master_key", "webui_session_secret", "database_url",
    "guardian_database_url", "log_level", "log_file", "media_dir",
}


def _ui_fields() -> set[str]:
    return {f.name for g in SETTINGS_GROUPS for f in g.fields}


def test_every_setting_is_editable_from_the_admin():
    """Требование владельца: «весь функционал для локального админа в админке».
    Поле, забытое в SETTINGS_GROUPS, правится только через .env — то есть
    фактически недоступно."""
    missing = set(Settings.model_fields) - _ui_fields() - set(SECRET_FIELD_NAMES)
    missing -= _DELIBERATELY_NOT_IN_UI
    assert not missing, f"поля Settings без формы в админке: {sorted(missing)}"


def test_admin_has_no_fields_that_do_not_exist_in_settings():
    """Опечатка в имени поля — самая тихая из возможных: форма сохраняется,
    значение уходит в БД и не применяется никогда."""
    ghosts = _ui_fields() - set(Settings.model_fields) - set(SECRET_FIELD_NAMES)
    assert not ghosts, f"поля в админке без соответствия в Settings: {sorted(ghosts)}"


def test_every_secret_has_a_label_and_a_hint():
    """Без подписи секрет выводится сырым именем поля, без подсказки —
    непонятно, где его брать (`telegraph_access_token` так и висел)."""
    no_label = [s for s in SECRET_FIELD_NAMES if s not in SECRET_LABELS]
    no_hint = [s for s in SECRET_FIELD_NAMES if s not in SECRET_HINTS]
    assert not no_label, f"секреты без подписи: {no_label}"
    assert not no_hint, f"секреты без подсказки: {no_hint}"


def test_every_setting_field_has_a_translated_label():
    """Отсутствующий ключ i18n рендерится прямо в интерфейс как [ключ]."""
    missing = [
        f"settings.field.{f.name}.label"
        for g in SETTINGS_GROUPS for f in g.fields
        if f"settings.field.{f.name}.label" not in STRINGS
    ]
    assert not missing, f"поля без перевода подписи: {missing}"


def test_no_translation_is_russian_only():
    missing_en = [k for k, v in STRINGS.items() if not v.get("en", "").strip()]
    assert not missing_en, f"ключи без английского: {missing_en[:10]}"


def test_placeholders_match_between_languages():
    """Расхождение плейсхолдеров роняет .format() уже в рантайме, и только
    на одном из языков — то есть у половины пользователей."""
    ph = re.compile(r"\{(\w+)\}")
    bad = {
        k: (sorted(set(ph.findall(v.get("ru", "")))), sorted(set(ph.findall(v.get("en", "")))))
        for k, v in STRINGS.items()
        if set(ph.findall(v.get("ru", ""))) != set(ph.findall(v.get("en", "")))
    }
    assert not bad, f"расходятся плейсхолдеры: {bad}"
