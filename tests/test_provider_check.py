"""Кнопка «Проверить подключение к ИИ» (сделано 2026-08-22).

ЗАЧЕМ ОНА. Провайдера настраивали вслепую: вписал адрес, ключ и модель — и
узнал, верно ли, по первому реальному посту, то есть через часы. Разбор
подключения OmniRoute на стенде занял полдня и вскрыл три ошибки подряд,
каждую из которых эта проверка показывает за секунду:

* в имени модели стоял `U+2011 NON-BREAKING HYPHEN` вместо обычного дефиса —
  скопировано из чата, глазами не отличить;
* имя модели не принималось вовсе: провайдер требует префикс поставщика;
* модель эмбеддингов отвечала «No credentials for embedding provider».
"""

from __future__ import annotations

import pytest

from tg_repost.config import invalidate_settings_cache
from tg_repost.rewriter.probe import check_provider, suspicious_characters


class FakeModels:
    def __init__(self, ids: list[str]) -> None:
        self._ids = ids

    async def list(self):
        data = [type("M", (), {"id": model_id})() for model_id in self._ids]
        return type("Page", (), {"data": data})()


class FakeCompletions:
    def __init__(self, fail_for: set[str] | None = None) -> None:
        self.fail_for = fail_for or set()
        self.asked: list[str] = []

    async def create(self, *, model, messages, max_tokens):
        self.asked.append(model)
        if model in self.fail_for:
            raise RuntimeError(f"{{'message': 'Unknown model {model}'}}")
        return type("R", (), {"model": model})()


class FakeEmbeddings:
    def __init__(self, works: bool = True) -> None:
        self.works = works
        self.asked: list[str] = []

    async def create(self, *, model, input):
        self.asked.append(model)
        if not self.works:
            raise RuntimeError("{'message': 'No credentials for embedding provider'}")
        item = type("E", (), {"embedding": [0.1] * 1024})()
        return type("R", (), {"data": [item]})()


class FakeClient:
    def __init__(self, *, models: list[str], fail_for: set[str] | None = None,
                 embeddings_work: bool = True) -> None:
        self.models = FakeModels(models)
        self.completions = FakeCompletions(fail_for)
        self.chat = type("Chat", (), {"completions": self.completions})()
        self.embeddings = FakeEmbeddings(embeddings_work)


@pytest.fixture
def provider(monkeypatch):
    """Подставной провайдер вместо настоящего клиента OpenAI."""
    from tg_repost.rewriter import probe

    holder: dict[str, FakeClient] = {}

    def install(**kwargs):
        client = FakeClient(**kwargs)
        holder["client"] = client
        monkeypatch.setattr(probe, "AsyncOpenAI", lambda **_: client)
        return client

    monkeypatch.setenv("OPENAI_API_KEY", "sk-заглушка")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://омнироут/v1")
    monkeypatch.setenv("OPENAI_MODEL", "рабочая-модель")
    monkeypatch.setenv("SEMANTIC_DEDUP_ENABLED", "false")
    invalidate_settings_cache()
    yield install, monkeypatch
    invalidate_settings_cache()


# --- невидимые символы ---


def test_non_breaking_hyphen_is_spotted():
    """ТОТ САМЫЙ СЛУЧАЙ СО СТЕНДА: имя скопировали из чата."""
    found = suspicious_characters("DeepSeek‑V3")

    assert found, "неразрывный дефис не замечен — а глазами его не отличить"
    assert "U+2011" in found[0]


def test_ordinary_name_is_not_flagged():
    """Обратная проверка: обычное имя не должно объявляться подозрительным."""
    assert suspicious_characters("hf/deepseek-ai/DeepSeek-V3") == []


@pytest.mark.asyncio
async def test_invisible_character_fails_the_check_without_calling_provider(provider):
    """Такую модель незачем даже спрашивать — сразу видно, что имя битое."""
    install, monkeypatch = provider
    monkeypatch.setenv("OPENAI_MODEL", "DeepSeek‑V3")
    invalidate_settings_cache()
    client = install(models=["DeepSeek-V3"])

    result = await check_provider()

    assert not result.ok
    broken = [s for s in result.steps if not s.ok]
    assert any("невидимые символы" in s.detail for s in broken)
    assert client.completions.asked == [], "битую модель всё равно спросили"


# --- обычные исходы ---


@pytest.mark.asyncio
async def test_healthy_setup_reports_success(provider):
    install, _ = provider
    client = install(models=["рабочая-модель", "другая"])

    result = await check_provider()

    assert result.ok, [f"{s.title}: {s.detail}" for s in result.steps if not s.ok]
    assert result.base_url == "http://омнироут/v1"
    assert client.completions.asked == ["рабочая-модель"]


@pytest.mark.asyncio
async def test_missing_key_is_explained_instead_of_failing_silently(provider):
    """Пустой ключ — частый случай с локальными серверами: они ключей не
    требуют, и владелец оставляет поле пустым. Запрос при этом не уходит
    вовсе, поэтому объяснить надо словами, а не кодом ошибки."""
    install, monkeypatch = provider
    monkeypatch.setenv("OPENAI_API_KEY", "")
    invalidate_settings_cache()
    install(models=[])

    result = await check_provider()

    assert not result.ok
    assert "заглушку" in result.steps[0].detail


@pytest.mark.asyncio
async def test_provider_error_is_shown_in_plain_words(provider):
    """Провайдер возвращает простыню JSON — на странице должна остаться суть."""
    install, _ = provider
    install(models=["другая"], fail_for={"рабочая-модель"})

    result = await check_provider()

    failed = [s for s in result.steps if not s.ok]
    assert failed, "отказ модели не показан"
    assert "Unknown model" in failed[0].detail
    assert "{" not in failed[0].detail, "в интерфейс уехал сырой JSON"


# --- роли ---


@pytest.mark.asyncio
async def test_each_distinct_model_is_checked_once(provider):
    """Роли с одинаковой моделью не должны стоить четырёх запросов, а роль со
    своей моделью обязана быть проверена отдельно — иначе опечатка в ней
    вскроется на первом же посте."""
    install, monkeypatch = provider
    monkeypatch.setenv("OPENAI_MODEL_EDITOR", "модель-редактора")
    invalidate_settings_cache()
    client = install(models=["рабочая-модель", "модель-редактора"])

    result = await check_provider()

    assert client.completions.asked == ["рабочая-модель", "модель-редактора"], (
        f"спрошено не то: {client.completions.asked}"
    )
    assert result.ok
    editor_step = [s for s in result.steps if "модель-редактора" in s.title]
    assert editor_step and "редактор" in editor_step[0].title


# --- эмбеддинги ---


@pytest.mark.asyncio
async def test_embeddings_checked_only_when_dedup_is_on(provider):
    install, monkeypatch = provider
    monkeypatch.setenv("SEMANTIC_DEDUP_ENABLED", "true")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "bge-m3")
    invalidate_settings_cache()
    client = install(models=["рабочая-модель"])

    result = await check_provider()

    assert client.embeddings.asked == ["bge-m3"]
    assert any("Эмбеддинги" in s.title for s in result.steps)
    assert result.ok


@pytest.mark.asyncio
async def test_broken_embeddings_do_not_hide_working_chat(provider):
    """Ровно случай со стенда: текст ходит, эмбеддинги нет. Владелец должен
    увидеть и то, и другое — иначе решит, что «всё сломалось»."""
    install, monkeypatch = provider
    monkeypatch.setenv("SEMANTIC_DEDUP_ENABLED", "true")
    invalidate_settings_cache()
    install(models=["рабочая-модель"], embeddings_work=False)

    result = await check_provider()

    assert not result.ok
    chat_step = [s for s in result.steps if "рабочая-модель" in s.title]
    assert chat_step and chat_step[0].ok, "рабочий чат показан как сломанный"
    embed_step = [s for s in result.steps if "Эмбеддинги" in s.title]
    assert embed_step and not embed_step[0].ok


# --- страница ---


def test_check_is_reachable_from_the_settings_page():
    """Кнопка должна быть на странице: проверка, до которой нельзя дойти, не
    существует для владельца."""
    from tests.test_app_routes import _bootstrap, _client

    client = _client()
    _bootstrap(client)

    page = client.get("/settings")

    assert "/settings/check-provider" in page.text, "кнопки проверки нет"


def test_check_is_not_triggered_by_a_plain_get():
    """Проверка делает ПЛАТНЫЕ вызовы наружу. На GET такое вешать нельзя —
    его дёргает предзагрузка ссылок браузером и любой обход страниц."""
    from tests.test_app_routes import _bootstrap, _client

    client = _client()
    _bootstrap(client)

    response = client.get("/settings/check-provider")

    assert response.status_code == 405, "проверка доступна по GET"
