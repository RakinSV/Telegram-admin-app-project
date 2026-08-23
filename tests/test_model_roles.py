"""Своя модель для каждой роли (сделано 2026-08-22 по просьбе владельца).

ЗАЧЕМ. Восемь ИИ-функций системы ходили через одну модель. Это неудобно там,
где задачи разной сложности: фактчек редактора выигрывает от модели
посильнее — его ошибка уходит в опубликованный пост, — а выбор поискового
запроса или строчка дайджеста прекрасно делаются дешёвой.

ПОЧЕМУ ПЕРЕОПРЕДЕЛЕНИЯ, А НЕ ПОЛНЫЙ НАБОР. Пустое поле означает «как
основная». Иначе на чистой установке пришлось бы заполнять четыре поля вместо
одного, и три из них — одним и тем же значением.

Роли:

* основная — рерайт поста (журналист) и статья на Telegraph;
* редактор — рецензия и правка в редакции двух агентов (F40);
* квизы — вопросы к постам для Engage;
* вспомогательная — ключевые слова, отбор источников (F16), текст нативной
  рекламы (F21), запрос для генератора обложки, сводка дайджеста (F20).
"""

from __future__ import annotations

import pytest

from tg_repost.config import invalidate_settings_cache
from tg_repost.rewriter.client import (
    ROLE_AUX,
    ROLE_EDITOR,
    ROLE_MAIN,
    ROLE_QUIZ,
    model_for_role,
)


@pytest.fixture
def settings_env(monkeypatch):
    """Настройки задаются переменными среды и сбрасываются после теста."""
    monkeypatch.setenv("OPENAI_MODEL", "основная-модель")
    invalidate_settings_cache()
    yield monkeypatch
    invalidate_settings_cache()


def test_all_roles_fall_back_to_the_main_model(settings_env):
    """Ничего не заполнено — все роли на основной модели, как было раньше."""
    for role in (ROLE_MAIN, ROLE_EDITOR, ROLE_QUIZ, ROLE_AUX):
        assert model_for_role(role) == "основная-модель", f"роль {role}"


def test_editor_can_use_a_stronger_model(settings_env):
    settings_env.setenv("OPENAI_MODEL_EDITOR", "модель-посильнее")
    invalidate_settings_cache()

    assert model_for_role(ROLE_EDITOR) == "модель-посильнее"
    # Остальные роли не задеты.
    assert model_for_role(ROLE_MAIN) == "основная-модель"
    assert model_for_role(ROLE_QUIZ) == "основная-модель"
    assert model_for_role(ROLE_AUX) == "основная-модель"


def test_auxiliary_tasks_can_use_a_cheap_model(settings_env):
    settings_env.setenv("OPENAI_MODEL_AUX", "дешёвая-модель")
    invalidate_settings_cache()

    assert model_for_role(ROLE_AUX) == "дешёвая-модель"
    assert model_for_role(ROLE_MAIN) == "основная-модель"


def test_blank_override_means_the_main_model(settings_env):
    """Пробелы — это не «модель по имени пробел». Форма настроек отправляет
    все поля группы, и пустое приходит само собой."""
    settings_env.setenv("OPENAI_MODEL_QUIZ", "   ")
    invalidate_settings_cache()

    assert model_for_role(ROLE_QUIZ) == "основная-модель"


def test_unknown_role_falls_back_instead_of_failing(settings_env):
    """Опечатка в имени роли не должна ронять рерайт — лучше основная модель,
    чем исключение посреди публикации."""
    assert model_for_role("такой-роли-нет") == "основная-модель"


# --- проводка до реальных вызовов ---


@pytest.mark.asyncio
async def test_editor_review_asks_for_the_editor_model(settings_env, monkeypatch):
    """ГЛАВНАЯ ПРОВЕРКА: настройка бесполезна, если роль не доходит до вызова.

    Смотрим, с какой моделью реально ушёл запрос рецензии.
    """
    settings_env.setenv("OPENAI_MODEL_EDITOR", "модель-редактора")
    invalidate_settings_cache()

    from tg_repost.rewriter import client as client_module

    asked: list[str] = []

    class FakeCompletions:
        async def create(self, *, model, messages, temperature):
            asked.append(model)
            usage = type("U", (), {"prompt_tokens": 1, "completion_tokens": 1})()
            message = type("M", (), {"content": "рецензия"})()
            choice = type("C", (), {"message": message})()
            return type("R", (), {"choices": [choice], "usage": usage})()

    client = client_module.RewriterClient.__new__(client_module.RewriterClient)
    client._client = type("Cl", (), {"chat": type("Ch", (), {
        "completions": FakeCompletions()})()})()
    client._model = "основная-модель"

    await client.rewrite_with_prompt("промпт", temperature=0.2, role=ROLE_EDITOR)

    assert asked == ["модель-редактора"], (
        f"запрос ушёл с моделью {asked} — роль редактора не доходит до вызова"
    )


@pytest.mark.asyncio
async def test_auxiliary_call_asks_for_the_aux_model(settings_env):
    """`complete()` обслуживает все мелкие поручения и роли не принимает —
    она у него всегда вспомогательная. Проверяем, что это так и есть."""
    settings_env.setenv("OPENAI_MODEL_AUX", "модель-мелочей")
    invalidate_settings_cache()

    from tg_repost.rewriter import client as client_module

    asked: list[str] = []

    class FakeCompletions:
        async def create(self, *, model, messages, temperature):
            asked.append(model)
            message = type("M", (), {"content": "ответ"})()
            choice = type("C", (), {"message": message})()
            return type("R", (), {"choices": [choice], "usage": None})()

    client = client_module.RewriterClient.__new__(client_module.RewriterClient)
    client._client = type("Cl", (), {"chat": type("Ch", (), {
        "completions": FakeCompletions()})()})()
    client._model = "основная-модель"

    await client.complete("подскажи ключевые слова")

    assert asked == ["модель-мелочей"]


# --- достижимость ---


def test_role_fields_are_on_the_settings_page():
    """Поля, до которых нельзя дойти, не существуют для владельца."""
    from tg_repost.webui.settings_store import SETTINGS_GROUPS

    names = {f.name for group in SETTINGS_GROUPS for f in group.fields}
    for field in ("openai_model_editor", "openai_model_quiz", "openai_model_aux"):
        assert field in names, f"{field} никуда не выведено"


# --- роль должна доходить ИЗ РЕАЛЬНОГО МЕСТА ВЫЗОВА ---


@pytest.mark.asyncio
async def test_editorial_pipeline_really_asks_for_the_editor_model(settings_env,
                                                                   monkeypatch):
    """ПРОВЕРКА ПУТИ, А НЕ ФУНКЦИИ.

    Тест на `rewrite_with_prompt` показывает только, что метод умеет принимать
    роль. Если из `editorial.py` её перестанут передавать, настройка станет
    мёртвой — и обычный тест этого не заметит. Диверсия это подтвердила:
    удаление `role=ROLE_EDITOR` из места вызова не роняло ничего.

    Здесь запускается ВЕСЬ редакционный цикл на поддельном клиенте, и
    проверяется, с какой моделью ушла именно рецензия.
    """
    settings_env.setenv("OPENAI_MODEL_EDITOR", "модель-редактора")
    settings_env.setenv("EDITORIAL_MAX_ROUNDS", "1")
    settings_env.setenv("EDITORIAL_WEB_VERIFY_ENABLED", "false")
    invalidate_settings_cache()

    from tg_repost.rewriter import editorial
    from tg_repost.rewriter.client import RewriteResult

    calls: list[tuple[str, str]] = []

    class FakeClient:
        async def rewrite(self, *args, **kwargs):
            calls.append(("рерайт", model_for_role(ROLE_MAIN)))
            return RewriteResult(text="черновик", prompt_tokens=1, completion_tokens=1)

        async def rewrite_with_prompt(self, prompt, *, temperature=None,
                                      role=ROLE_MAIN):
            calls.append(("по промпту", model_for_role(role)))
            # Ответ редактора в ожидаемом формате: правок не требуется.
            return RewriteResult(text="ВЕРДИКТ: ок", prompt_tokens=1,
                                 completion_tokens=1)

    await editorial.editorial_rewrite(
        FakeClient(), original="исходный текст", link_content="",
        prompt_name="default", language=None,
    )

    by_prompt = [model for kind, model in calls if kind == "по промпту"]
    assert by_prompt, "редакция не сделала ни одного вызова по промпту"
    assert by_prompt[0] == "модель-редактора", (
        f"рецензия ушла с моделью {by_prompt[0]!r} — роль редактора не "
        f"передаётся из editorial.py, настройка мертва"
    )
    # Черновик пишет журналист — он на основной модели.
    assert ("рерайт", "основная-модель") in calls


@pytest.mark.asyncio
async def test_quiz_builder_really_asks_for_the_quiz_model(settings_env):
    """То же для квизов: роль должна доходить из `quiz.py`, а не только
    поддерживаться методом клиента."""
    settings_env.setenv("OPENAI_MODEL_QUIZ", "модель-квизов")
    invalidate_settings_cache()

    from tg_repost.rewriter import quiz
    from tg_repost.rewriter.client import RewriteResult

    asked: list[str] = []

    class FakeClient:
        async def rewrite_with_prompt(self, prompt, *, temperature=None,
                                      role=ROLE_MAIN):
            asked.append(model_for_role(role))
            return RewriteResult(
                text='{"question": "Вопрос?", "options": ["А", "Б", "В"], '
                     '"correct_index": 0, "explanation": "потому что"}',
                prompt_tokens=1, completion_tokens=1,
            )

    await quiz.generate_quiz(FakeClient(), "текст поста")

    assert asked == ["модель-квизов"], (
        f"квиз ушёл с моделью {asked} — роль не передаётся из quiz.py"
    )
