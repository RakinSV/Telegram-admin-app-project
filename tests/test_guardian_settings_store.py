"""Тесты guardian/settings_store.py + оверлея bot_config в
guardian.config.get_guardian_settings() — приоритет БД поверх .env,
сохранение типов (int/float/bool/str), не влияет на не-перезаписанные поля."""

from __future__ import annotations

import pytest

from guardian import settings_store
from guardian.config import get_guardian_settings, invalidate_settings_cache
from guardian.db.models import BotConfig
from guardian.db.session import session_scope


@pytest.fixture(autouse=True)
def _clear_bot_config():
    with session_scope() as session:
        session.query(BotConfig).delete()
    invalidate_settings_cache()
    yield
    with session_scope() as session:
        session.query(BotConfig).delete()
    invalidate_settings_cache()


def test_effective_value_falls_back_to_env_default():
    field = next(
        f
        for g in settings_store.SETTINGS_GROUPS
        for f in g.fields
        if f.name == "spam_mode"
    )
    assert settings_store.effective_value(field) == "keywords"


def test_save_setting_overrides_env_default():
    settings_store.save_setting("spam_mode", "hybrid", "str")
    assert get_guardian_settings().spam_mode == "hybrid"


def test_save_setting_preserves_int_type():
    settings_store.save_setting("warn_threshold_mute", 7, "int")
    settings = get_guardian_settings()
    assert settings.warn_threshold_mute == 7
    assert isinstance(settings.warn_threshold_mute, int)


def test_save_setting_preserves_float_type():
    settings_store.save_setting("ai_spam_confidence_threshold", 0.42, "float")
    settings = get_guardian_settings()
    assert settings.ai_spam_confidence_threshold == pytest.approx(0.42)
    assert isinstance(settings.ai_spam_confidence_threshold, float)


def test_save_setting_preserves_bool_type():
    settings_store.save_setting("allow_forwards", False, "bool")
    settings = get_guardian_settings()
    assert settings.allow_forwards is False


def test_save_setting_unrelated_field_untouched():
    settings_store.save_setting("spam_mode", "ai", "str")
    settings = get_guardian_settings()
    assert settings.warn_threshold_ban == 4  # дефолт из .env, не тронут


def test_save_setting_unknown_key_raises():
    with pytest.raises(ValueError):
        settings_store.save_setting("not_a_real_field", 1, "int")


def test_save_setting_overwrites_existing_value():
    settings_store.save_setting("spam_mode", "ai", "str")
    settings_store.save_setting("spam_mode", "hybrid", "str")
    assert get_guardian_settings().spam_mode == "hybrid"
    with session_scope() as session:
        assert (
            session.query(BotConfig).filter(BotConfig.key == "spam_mode").count() == 1
        )


def test_captcha_questions_and_allowed_domains_not_treated_as_settings_overlay():
    """`bot_config` хранит не только настройки — `captcha_questions` (G01) и
    `allowed_domains` (G04) там же, но это НЕ поля `GuardianSettings` и не
    должны попадать в оверлей (`_db_overrides` фильтрует по `model_fields`)."""
    with session_scope() as session:
        session.add(
            BotConfig(key="allowed_domains", value='["example.com"]', updated_by="test")
        )
    settings = get_guardian_settings()
    assert not hasattr(settings, "allowed_domains")
