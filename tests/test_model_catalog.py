"""Выбор модели из списка провайдера (по просьбе владельца 2026-08-23).

ЗАЧЕМ. Модель вписывалась руками, и это стоило полдня разбора: в имени
`DeepSeek‑V3`, скопированном из чата, оказался неразрывный дефис U+2011 —
глазами не отличить, а провайдер такой модели не знает. Плюс у OmniRoute 368
моделей, и какие из них есть, узнать было неоткуда.

ПОЧЕМУ ПОДСКАЗКА, А НЕ ЗАКРЫТЫЙ СПИСОК. Псевдонимы вроде `auto/cheap`
провайдер может не показывать в `/v1/models`, а работают они; локальный
llama.cpp вообще отдаёт одну строку с путём до gguf-файла. Закрытый список
запретил бы рабочие настройки.
"""

from __future__ import annotations

import json

import pytest

from tg_repost.config import invalidate_settings_cache
from tg_repost.rewriter.model_catalog import (
    ModelCatalog,
    cached_catalog,
    refresh_catalog,
)

LIVE_LIST = [
    "auto/cheap",
    "hf/deepseek-ai/DeepSeek-V3",
    "openrouter/baai/bge-m3",
    "openrouter/openai/text-embedding-3-small",
    "siliconflow/black-forest-labs/FLUX.1-schnell",
    "openrouter/google/gemini-3.1-flash-image-preview",
]


@pytest.fixture
def clean_settings(monkeypatch):
    from tg_repost.db.models import AppSetting
    from tg_repost.db.session import session_scope

    with session_scope() as session:
        session.query(AppSetting).delete()
    monkeypatch.setenv("OPENAI_BASE_URL", "http://омнироут/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-заглушка")
    invalidate_settings_cache()
    yield monkeypatch
    with session_scope() as session:
        session.query(AppSetting).delete()
    invalidate_settings_cache()


# --- раскладка по назначению ---


def test_models_are_split_by_purpose():
    """Провайдер не говорит, что умеет модель, — судим по имени. Для
    подсказки этого хватает."""
    catalog = ModelCatalog(models=tuple(LIVE_LIST), fetched_at=None)

    assert "auto/cheap" in catalog.chat
    assert "hf/deepseek-ai/DeepSeek-V3" in catalog.chat
    assert "openrouter/baai/bge-m3" in catalog.embedding
    assert "openrouter/openai/text-embedding-3-small" in catalog.embedding
    assert "siliconflow/black-forest-labs/FLUX.1-schnell" in catalog.image
    assert "openrouter/google/gemini-3.1-flash-image-preview" in catalog.image


def test_embedding_and_image_models_do_not_pollute_the_chat_list():
    """Иначе владелец выберет в поле рерайта модель эмбеддингов и получит
    отказ провайдера на первом же посте."""
    catalog = ModelCatalog(models=tuple(LIVE_LIST), fetched_at=None)

    for model in catalog.chat:
        assert "embed" not in model.lower()
        assert "flux" not in model.lower()


# --- кэш ---


def test_empty_cache_is_not_an_error(clean_settings):
    """Пока список не забирали, поля просто остаются текстовыми."""
    catalog = cached_catalog()

    assert catalog.models == ()
    assert catalog.fetched_at is None


def test_broken_cache_does_not_break_the_settings_page(clean_settings):
    """Кэш — это подсказка. Повреждённая подсказка не должна ронять
    страницу, на которой её показывают."""
    from tg_repost.webui.settings_store import save_setting

    save_setting("provider_models_cache", "{это не json", "str")
    invalidate_settings_cache()

    catalog = cached_catalog()

    assert catalog.models == ()


@pytest.mark.asyncio
async def test_refresh_stores_the_list(clean_settings, monkeypatch):
    from tg_repost.rewriter import model_catalog

    class FakeModels:
        async def list(self):
            data = [type("M", (), {"id": model_id})() for model_id in LIVE_LIST]
            return type("Page", (), {"data": data})()

    monkeypatch.setattr(model_catalog, "AsyncOpenAI",
                        lambda **_: type("C", (), {"models": FakeModels()})())

    catalog = await refresh_catalog()

    assert len(catalog.models) == len(LIVE_LIST)
    assert catalog.fetched_at is not None
    # И это же должно читаться обратно из кэша — иначе кнопка бесполезна.
    invalidate_settings_cache()
    assert set(cached_catalog().models) == set(LIVE_LIST)


@pytest.mark.asyncio
async def test_refresh_deduplicates_and_sorts(clean_settings, monkeypatch):
    from tg_repost.rewriter import model_catalog

    class FakeModels:
        async def list(self):
            ids = ["b/model", "a/model", "b/model"]
            data = [type("M", (), {"id": model_id})() for model_id in ids]
            return type("Page", (), {"data": data})()

    monkeypatch.setattr(model_catalog, "AsyncOpenAI",
                        lambda **_: type("C", (), {"models": FakeModels()})())

    catalog = await refresh_catalog()

    assert catalog.models == ("a/model", "b/model")


@pytest.mark.asyncio
async def test_provider_failure_is_raised_not_swallowed(clean_settings,
                                                        monkeypatch):
    """Кнопку нажал владелец — он должен увидеть причину, а не пустой
    список без объяснений."""
    from tg_repost.rewriter import model_catalog

    class FailingModels:
        async def list(self):
            raise RuntimeError("Invalid API key")

    monkeypatch.setattr(model_catalog, "AsyncOpenAI",
                        lambda **_: type("C", (), {"models": FailingModels()})())

    with pytest.raises(RuntimeError):
        await refresh_catalog()


# --- страница ---


def test_refresh_button_is_on_the_settings_page():
    from tests.test_app_routes import _bootstrap, _client

    client = _client()
    _bootstrap(client)

    page = client.get("/settings")

    assert "/settings/refresh-models" in page.text, "кнопки обновления нет"


def test_refresh_is_not_triggered_by_a_plain_get():
    """Обработчик ходит в сеть. На GET такое вешать нельзя — его дёргает
    предзагрузка ссылок браузером и любой обход страниц."""
    from tests.test_app_routes import _bootstrap, _client

    client = _client()
    _bootstrap(client)

    response = client.get("/settings/refresh-models")

    assert response.status_code == 405


def test_model_fields_offer_the_cached_list(clean_settings):
    """Смысл всей затеи: список должен доехать до поля на странице."""
    from tests.test_app_routes import _bootstrap, _client
    from tg_repost.webui.settings_store import save_setting

    save_setting(
        "provider_models_cache",
        json.dumps({"fetched_at": "2026-08-23T10:00:00+00:00",
                    "models": LIVE_LIST}),
        "str",
    )
    invalidate_settings_cache()

    client = _client()
    _bootstrap(client)
    page = client.get("/settings")

    assert "models-openai_model" in page.text, "подсказки у поля модели нет"
    assert "auto/cheap" in page.text, "список моделей не доехал до страницы"
    assert "openrouter/baai/bge-m3" in page.text
