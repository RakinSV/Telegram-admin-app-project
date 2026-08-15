"""Петля обучения антиспама (F57).

Две вещи здесь важнее остального, и обе легко сделать неправильно:

1. **Баланс примеров.** Размечать тянет прежде всего спам — он раздражает,
   его замечают. Если сложить примеры как есть, в промпт уедут двадцать
   спамов и один нормальный текст, и модель научится называть спамом всё
   подряд. Фильтр станет агрессивнее, а не точнее — то есть фича сделает
   хуже, чем было.
2. **Защита лог-канала от потока.** Спамер с пятьюдесятью одинаковыми
   сообщениями не должен превращать канал в ленту из пятидесяти одинаковых
   запросов: владелец перестанет читать её целиком, вместе с полезными.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from guardian import spam_reviews_repo as repo
from guardian.db.models import SpamReview
from guardian.db.session import session_scope

CHAT = -100777001


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(SpamReview).delete()

    _wipe()
    yield
    _wipe()


def _enqueue(text: str, kind: str = "no_verdict", **kw) -> int | None:
    return repo.enqueue(chat_id=CHAT, user_id=1, text=text, kind=kind, **kw)


def _label(text: str, label: str, *, minutes_ago: int = 0) -> None:
    review_id = _enqueue(text)
    assert review_id is not None
    repo.set_label(review_id, label)
    if minutes_ago:
        with session_scope() as session:
            row = session.get(SpamReview, review_id)
            assert row is not None
            row.labeled_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)


# --- нормализация и защита от потока ---


def test_hash_ignores_case_and_whitespace():
    """Спамеры рассылают одно и то же с косметическими отличиями."""
    assert repo.normalized_hash("Купи   КУРС") == repo.normalized_hash("купи курс")
    assert repo.normalized_hash(" купи курс\n") == repo.normalized_hash("купи курс")


def test_duplicate_pending_is_not_queued_twice():
    """Главная защита лог-канала от потока."""
    first = _enqueue("Заработок от 1000$ в день")
    second = _enqueue("ЗАРАБОТОК от 1000$   в день")

    assert first is not None
    assert second is None
    with session_scope() as session:
        assert session.query(SpamReview).count() == 1


def test_same_text_can_be_queued_again_after_labeling():
    """Уже разобранный текст, пришедший снова, — это новый случай.

    Решение владельца могло измениться, и молчать о повторе значило бы
    прятать от него как раз то, на чём он однажды сомневался.
    """
    first = _enqueue("Пиши в личку по поводу заработка")
    assert first is not None
    repo.set_label(first, repo.LABEL_SPAM)

    second = _enqueue("пиши в личку по поводу заработка")

    assert second is not None


def test_different_texts_are_queued_separately():
    assert _enqueue("Первый текст") is not None
    assert _enqueue("Совсем другой текст") is not None


def test_text_is_truncated_on_write():
    review_id = _enqueue("а" * 5000)
    with session_scope() as session:
        row = session.get(SpamReview, review_id)
        assert row is not None
        assert len(row.message_text) == repo.MAX_TEXT_LEN


# --- разметка ---


def test_set_label_records_decision_and_time():
    review_id = _enqueue("сомнительное сообщение")
    assert repo.set_label(review_id, repo.LABEL_SPAM) is True

    with session_scope() as session:
        row = session.get(SpamReview, review_id)
        assert row is not None
        assert row.label == repo.LABEL_SPAM
        assert row.labeled_at is not None


def test_unknown_label_is_rejected():
    """Иначе опечатка в callback_data тихо попала бы в обучающую выборку."""
    review_id = _enqueue("текст")
    assert repo.set_label(review_id, "может_быть") is False


def test_set_label_on_missing_review_returns_false():
    assert repo.set_label(999999, repo.LABEL_SPAM) is False


def test_pending_count_excludes_labeled():
    _enqueue("первый")
    second = _enqueue("второй")
    repo.set_label(second, repo.LABEL_HAM)

    assert repo.pending_count() == 1


def test_chat_of_returns_source_chat():
    """Право размечать определяется админством в ИСХОДНОМ чате."""
    review_id = _enqueue("текст")
    assert repo.chat_of(review_id) == CHAT
    assert repo.chat_of(999999) is None


# --- баланс обучающей выборки ---


def test_examples_are_balanced_between_labels():
    """Двадцать спамов и один «не спам» не должны уехать в промпт как есть.

    Модель научилась бы ровно одному — называть спамом всё подряд.
    """
    for i in range(20):
        _label(f"спам номер {i}", repo.LABEL_SPAM)
    _label("обычное сообщение", repo.LABEL_HAM)

    examples = repo.few_shot_examples(limit_per_label=5)

    assert sum(1 for e in examples if e.is_spam) == 5
    assert sum(1 for e in examples if not e.is_spam) == 1


def test_examples_prefer_recent():
    """Спам меняется — прошлогодние схемы учат вчерашней войне."""
    _label("старый спам", repo.LABEL_SPAM, minutes_ago=10_000)
    _label("свежий спам", repo.LABEL_SPAM, minutes_ago=1)

    examples = repo.few_shot_examples(limit_per_label=1)

    assert [e.text for e in examples] == ["свежий спам"]


def test_unlabeled_never_enter_the_training_set():
    _enqueue("никто не разметил")

    assert repo.few_shot_examples() == []


# --- блок для промпта ---


def test_empty_examples_produce_empty_block():
    """На чистой установке промпт не должен меняться вообще."""
    assert repo.format_examples_block([]) == ""


def test_block_marks_both_verdicts():
    block = repo.format_examples_block([
        repo.Example(text="купи курс", is_spam=True),
        repo.Example(text="привет всем", is_spam=False),
    ])

    assert "купи курс" in block and "СПАМ" in block
    assert "привет всем" in block and "НЕ СПАМ" in block


def test_block_respects_char_cap():
    """Потолок обязателен: промпт оплачивается на КАЖДОМ вызове.

    Без него стоимость модерации тихо росла бы вместе с числом размеченных
    примеров — фича дорожала бы тем сильнее, чем активнее ей пользуются.
    """
    many = [repo.Example(text="х" * 300, is_spam=True) for _ in range(50)]

    block = repo.format_examples_block(many, max_chars=1000)

    assert len(block) < 1500


def test_block_flattens_newlines():
    """Перевод строки внутри примера сбил бы разбор на стороне модели."""
    block = repo.format_examples_block(
        [repo.Example(text="первая строка\nвторая строка", is_spam=True)]
    )

    assert "первая строка вторая строка" in block


# --- интеграция с классификатором ---


def _capture_prompt(monkeypatch) -> list[str]:
    """Перехватить промпт, уходящий в модель, не ходя в сеть."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    seen: list[str] = []

    async def _create(**kwargs):
        seen.append(kwargs["messages"][0]["content"])
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content='{"spam": false, "confidence": 0.1}')
            )],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=_create)))
    )
    monkeypatch.setattr(
        "guardian.filters.ai_filter.AsyncOpenAI", lambda **_kw: client, raising=True,
    )
    return seen


async def test_labeled_examples_reach_the_prompt(monkeypatch):
    """Ради этого фича и делалась: решения владельца влияют на классификатор."""
    from guardian.config import get_guardian_settings
    from guardian.filters import ai_filter

    monkeypatch.setattr(
        get_guardian_settings(), "spam_learning_enabled", True, raising=False,
    )
    _label("купи курс за 10000", repo.LABEL_SPAM)
    _label("ребята, всем привет", repo.LABEL_HAM)
    seen = _capture_prompt(monkeypatch)

    await ai_filter.classify("проверяемое сообщение")

    assert len(seen) == 1
    assert "купи курс за 10000" in seen[0]
    assert "ребята, всем привет" in seen[0]


async def test_prompt_unchanged_when_learning_disabled(monkeypatch):
    """Выключено — промпт не меняется вообще.

    Фича трогает поведение фильтра, поэтому по умолчанию выключена. Если
    выключатель не работает, все прочие тесты про баланс теряют смысл.
    """
    from guardian.config import get_guardian_settings
    from guardian.filters import ai_filter

    monkeypatch.setattr(
        get_guardian_settings(), "spam_learning_enabled", False, raising=False,
    )
    _label("купи курс за 10000", repo.LABEL_SPAM)
    seen = _capture_prompt(monkeypatch)

    await ai_filter.classify("проверяемое сообщение")

    assert len(seen) == 1
    assert "купи курс за 10000" not in seen[0]


async def test_prompt_has_no_block_without_any_labels(monkeypatch):
    """На чистой установке промпт остаётся ровно таким, каким был до F57."""
    from guardian.config import get_guardian_settings
    from guardian.filters import ai_filter

    monkeypatch.setattr(
        get_guardian_settings(), "spam_learning_enabled", True, raising=False,
    )
    seen = _capture_prompt(monkeypatch)

    await ai_filter.classify("проверяемое сообщение")

    assert "Примеры решений владельца" not in seen[0]
