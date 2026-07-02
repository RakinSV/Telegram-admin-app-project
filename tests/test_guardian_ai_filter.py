"""Тесты AI-классификатора спама Guardian (G09) — мокаем `AsyncOpenAI`,
без реального сетевого вызова."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from guardian.filters import ai_filter


def _fake_response(content: str, prompt_tokens: int = 100, completion_tokens: int = 20):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


def _patch_client(monkeypatch, response=None, side_effect=None):
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(return_value=response, side_effect=side_effect)
            )
        )
    )
    monkeypatch.setattr(ai_filter, "AsyncOpenAI", lambda **kwargs: fake_client)
    return fake_client


async def test_classify_spam_detected(monkeypatch):
    payload = json.dumps({"spam": True, "reason": "реклама", "confidence": 0.9})
    _patch_client(monkeypatch, response=_fake_response(payload))

    result = await ai_filter.classify("Купи крипту прямо сейчас!")

    assert result is not None
    assert result.is_spam is True
    assert result.reason == "реклама"
    assert result.confidence == 0.9
    assert result.cost_usd > 0


async def test_classify_not_spam(monkeypatch):
    payload = json.dumps({"spam": False, "reason": "", "confidence": 0.1})
    _patch_client(monkeypatch, response=_fake_response(payload))

    result = await ai_filter.classify("Какая сегодня погода?")

    assert result is not None
    assert result.is_spam is False


async def test_classify_invalid_json_returns_none(monkeypatch):
    _patch_client(monkeypatch, response=_fake_response("не json вообще"))

    result = await ai_filter.classify("что угодно")

    assert result is None


async def test_classify_missing_fields_returns_none(monkeypatch):
    _patch_client(monkeypatch, response=_fake_response(json.dumps({"spam": True})))

    result = await ai_filter.classify("что угодно")

    assert result is None  # нет "confidence" — KeyError поймана, fail-open


async def test_classify_api_error_returns_none(monkeypatch):
    _patch_client(monkeypatch, side_effect=RuntimeError("API недоступен"))

    result = await ai_filter.classify("что угодно")

    assert result is None


async def test_classify_cost_estimate_scales_with_tokens(monkeypatch):
    payload = json.dumps({"spam": False, "reason": "", "confidence": 0.1})
    _patch_client(
        monkeypatch,
        response=_fake_response(payload, prompt_tokens=1_000_000, completion_tokens=1_000_000),
    )

    result = await ai_filter.classify("текст")

    assert result is not None
    assert result.cost_usd == ai_filter._PRICE_PER_1M_INPUT_USD + ai_filter._PRICE_PER_1M_OUTPUT_USD
