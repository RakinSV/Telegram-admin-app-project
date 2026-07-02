"""AI-классификатор спама (G09) — режим `ai` и часть гибридного `hybrid` (G10).

Использует тот же OpenAI-совместимый клиент, что и рерайтер репост-бота
(`GuardianSettings.openai_*` — те же env-переменные, общий ключ, см.
GUARDIAN.md). Таймаут 3с, fail-open при ошибке/таймауте/невалидном ответе —
вызывающий код должен трактовать `None` как "пропустить, не удалять": при
неуверенности лучше пропустить спам, чем удалить легитимное сообщение."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from openai import AsyncOpenAI

from guardian.config import get_guardian_settings
from guardian.logging_conf import get_logger

logger = get_logger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "spam_classifier.txt"
_TIMEOUT_SECONDS = 3.0

# Ориентировочная цена gpt-4o-mini (не биллинг-грейд точность — только для
# приблизительной оценки в /stats, см. G11; не подстраивается под
# сконфигурированную модель, если оператор сменил её в .env).
_PRICE_PER_1M_INPUT_USD = 0.15
_PRICE_PER_1M_OUTPUT_USD = 0.60


@dataclass(frozen=True)
class ClassificationResult:
    is_spam: bool
    reason: str
    confidence: float
    cost_usd: float


@lru_cache
def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    return (
        prompt_tokens / 1_000_000 * _PRICE_PER_1M_INPUT_USD
        + completion_tokens / 1_000_000 * _PRICE_PER_1M_OUTPUT_USD
    )


async def classify(text: str) -> ClassificationResult | None:
    """Классифицировать сообщение. `None` — ошибка/таймаут/невалидный ответ,
    вызывающий код пропускает сообщение (fail-open, см. docstring модуля)."""
    settings = get_guardian_settings()
    prompt = _load_prompt().format(message_text=text)
    client = AsyncOpenAI(base_url=settings.openai_base_url, api_key=settings.openai_api_key)

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            timeout=_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 — любая ошибка API/таймаут → fail-open
        # Обрезка длины — некоторые ошибки нестандартных OPENAI_BASE_URL-прокси
        # могут отражать детали запроса в теле ошибки (найдено security-ревью);
        # тот же приём уже используется ниже для сырого ответа модели.
        logger.warning("AI-классификатор: ошибка вызова API (%s)", str(exc)[:200])
        return None

    raw = (response.choices[0].message.content or "").strip()
    usage = response.usage
    cost = _estimate_cost(
        usage.prompt_tokens if usage else 0, usage.completion_tokens if usage else 0
    )
    try:
        data = json.loads(raw)
        is_spam = bool(data["spam"])
        reason = str(data.get("reason", ""))
        confidence = float(data["confidence"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("AI-классификатор: невалидный JSON-ответ (%s): %r", exc, raw[:200])
        return None

    return ClassificationResult(is_spam=is_spam, reason=reason, confidence=confidence, cost_usd=cost)
