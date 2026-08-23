"""Проверка подключения к AI-провайдеру (по просьбе владельца 2026-08-22).

ЗАЧЕМ. Настроить провайдера можно только «вслепую»: вписал адрес, ключ и
модель — и узнал, верно ли, по первому реальному посту, то есть через часы.
Разбор подключения OmniRoute на стенде занял полдня и вскрыл три ошибки
подряд, каждую из которых эта проверка показала бы за секунду:

* в имени модели стоял `U+2011 NON-BREAKING HYPHEN` вместо обычного дефиса —
  скопировано из чата, глазами не отличить;
* имя модели вообще не принималось: провайдер требует префикс поставщика;
* модель эмбеддингов отвечала «No credentials for embedding provider».

ЧТО ПРОВЕРЯЕТСЯ. Список моделей (значит, адрес и ключ верны), затем короткий
вызов КАЖДОЙ настроенной модели — основной, редактора, квизов,
вспомогательной, — и эмбеддинги, если включён семантический дубль-чек.
Одинаковые модели проверяются один раз: на типовой настройке роли делят одну
модель, и четыре одинаковых запроса были бы просто платой ни за что.

ЦЕНА. Промпт в несколько слов и `max_tokens=5`. Это осознанно платный вызов —
поэтому проверка живёт на кнопке, а не на открытии страницы.
"""

from __future__ import annotations

import asyncio
import time
import unicodedata
from dataclasses import dataclass, field

from openai import AsyncOpenAI

from tg_repost.config import get_settings
from tg_repost.logging_conf import get_logger
from tg_repost.rewriter.client import (
    ROLE_AUX,
    ROLE_EDITOR,
    ROLE_MAIN,
    ROLE_QUIZ,
    model_for_role,
)

logger = get_logger(__name__)

# Ответ на проверку читать не нужно — важно, что он есть.
_PROBE_PROMPT = "ping"
_PROBE_MAX_TOKENS = 5
_STEP_TIMEOUT_SECONDS = 45

ROLE_TITLES = {
    ROLE_MAIN: "основная (рерайт, статья)",
    ROLE_EDITOR: "редактор-фактчекер",
    ROLE_QUIZ: "квизы",
    ROLE_AUX: "вспомогательные задачи",
}


@dataclass
class StepResult:
    """Один шаг проверки: что делали, получилось ли, сколько заняло."""

    title: str
    ok: bool
    detail: str
    millis: int = 0


@dataclass
class ProviderCheck:
    base_url: str
    steps: list[StepResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.steps) and all(step.ok for step in self.steps)


# Символы, которые ПРИТВОРЯЮТСЯ обычными: выглядят как дефис, слэш или
# пробел, но провайдер такой модели не знает. Приезжают вместе с именем,
# скопированным из чата или из вёрстки документации.
#
# Список закрытый и только про подделки ASCII. Соблазн «ругаться на всё
# не-ASCII» пришлось отбросить: имя модели теоретически может быть любым, а
# ложный отказ хуже пропущенной подсказки — он не даст проверить рабочую
# настройку.
_CONFUSABLE = {
    "‐": "дефис-юникод", "‑": "неразрывный дефис",
    "‒": "цифровое тире", "–": "короткое тире",
    "—": "длинное тире", "―": "горизонтальная черта",
    "−": "минус", "﹘": "малое тире", "﹣": "малый дефис",
    "－": "широкий дефис", "／": "широкий слэш",
    " ": "неразрывный пробел", " ": "цифровой пробел",
    " ": "тонкий пробел", " ": "узкий неразрывный пробел",
    "　": "идеографический пробел",
    "​": "нулевой пробел", "‌": "несоединитель",
    "‍": "соединитель", "⁠": "неразрывность нулевой ширины",
    "﻿": "метка порядка байтов",
}


def suspicious_characters(value: str) -> list[str]:
    """Невидимые двойники обычных символов в строке.

    Имя модели копируют из чата или из документации, и вместе с ним приезжает
    неразрывный дефис или неразрывный пробел. Глазами они неотличимы, а
    провайдер такой модели не знает. Ровно это и случилось на стенде:
    в `DeepSeek‑V3` стоял U+2011 вместо обычного дефиса, и разбирались с этим
    полдня.
    """
    found = []
    for char in value:
        if char not in _CONFUSABLE:
            continue
        name = unicodedata.name(char, "неизвестный символ")
        found.append(f"«{_CONFUSABLE[char]}» U+{ord(char):04X} ({name})")
    return found


def _short(error: BaseException) -> str:
    """Короткая суть ошибки: провайдеры возвращают простыню JSON.

    Берём значение поля `message` целиком — до закрывающей кавычки, а не «всё
    после двоеточия»: иначе в интерфейс уезжает хвост вида
    `', 'type': 'invalid_request_error', 'code': 'bad_request'}}`, который
    владельцу ничего не говорит.
    """
    text = str(error)
    marker = "'message': "
    if marker in text:
        tail = text.split(marker, 1)[1].lstrip()
        if tail[:1] in {"'", '"'}:
            quote = tail[0]
            closing = tail.find(quote, 1)
            tail = tail[1:closing] if closing > 0 else tail[1:]
        text = tail
    return text.strip().strip("'\"")[:300]


async def _timed(title: str, coro) -> StepResult:
    started = time.perf_counter()
    try:
        detail = await asyncio.wait_for(coro, timeout=_STEP_TIMEOUT_SECONDS)
        ok = True
    except TimeoutError:
        detail = f"нет ответа за {_STEP_TIMEOUT_SECONDS} с"
        ok = False
    except Exception as exc:  # noqa: BLE001 — показываем владельцу любую ошибку
        detail = _short(exc)
        ok = False
    return StepResult(title=title, ok=ok, detail=detail,
                      millis=int((time.perf_counter() - started) * 1000))


async def check_provider() -> ProviderCheck:
    """Проверить связку целиком. Исключений не бросает: каждый шаг сам себе
    отчёт, а страница настроек должна открыться в любом случае."""
    settings = get_settings()
    result = ProviderCheck(base_url=settings.openai_base_url)

    if not settings.openai_api_key:
        result.steps.append(StepResult(
            title="Ключ провайдера",
            ok=False,
            detail="ключ не задан — запрос не уйдёт вовсе, даже если провайдер "
                   "ключей не требует (пустой заголовок Authorization "
                   "отвергается клиентом). Впишите любую заглушку, например "
                   "sk-local.",
        ))
        return result

    client = AsyncOpenAI(
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        timeout=_STEP_TIMEOUT_SECONDS,
        max_retries=0,
    )

    known: set[str] = set()

    async def list_models() -> str:
        page = await client.models.list()
        for item in page.data:
            known.add(item.id)
        return f"провайдер отдал {len(known)} моделей"

    result.steps.append(await _timed("Адрес и ключ (/v1/models)", list_models()))

    # Роли, у которых модель отличается, проверяем по отдельности; одинаковые
    # — один раз, чтобы не платить четырежды за один и тот же ответ.
    seen: dict[str, list[str]] = {}
    for role in (ROLE_MAIN, ROLE_EDITOR, ROLE_QUIZ, ROLE_AUX):
        seen.setdefault(model_for_role(role), []).append(ROLE_TITLES[role])

    for model, roles in seen.items():
        title = f"Модель «{model}» — {', '.join(roles)}"
        weird = suspicious_characters(model)
        if weird:
            result.steps.append(StepResult(
                title=title,
                ok=False,
                detail="в имени модели невидимые символы: " + "; ".join(weird)
                       + ". Наберите имя руками, а не копируйте.",
            ))
            continue
        if known and model not in known:
            # Не отказ: у провайдера бывают псевдонимы, которых нет в списке.
            logger.info("Проверка провайдера: модели «%s» нет в списке", model)

        async def probe(name: str = model) -> str:
            response = await client.chat.completions.create(
                model=name,
                messages=[{"role": "user", "content": _PROBE_PROMPT}],
                max_tokens=_PROBE_MAX_TOKENS,
            )
            answered = getattr(response, "model", "") or name
            return f"ответила (провайдер вернул «{answered}»)"

        result.steps.append(await _timed(title, probe()))

    if settings.semantic_dedup_enabled:
        embedding_model = settings.openai_embedding_model

        async def probe_embedding() -> str:
            response = await client.embeddings.create(
                model=embedding_model, input="ping",
            )
            return f"вектор длиной {len(response.data[0].embedding)}"

        result.steps.append(await _timed(
            f"Эмбеддинги «{embedding_model}» — семантический дубль-чек",
            probe_embedding(),
        ))

    return result
