"""Клиент рерайта (F06) поверх OpenAI-совместимого API.

Провайдер меняется через `.env` (`OPENAI_BASE_URL`/`OPENAI_API_KEY`/
`OPENAI_MODEL`), не в коде. Промпт-шаблоны хранятся в файлах
(`rewriter/prompts/*.txt`), а не хардкодятся, чтобы их можно было итерировать
без передеплоя. Стиль-профили (F15) — это разные файлы промптов.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import httpx
from openai import AsyncOpenAI

from tg_repost import languages
from tg_repost import proxy as proxy_module
from tg_repost.config import get_settings
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"

# Маркеры ошибки оплаты/баланса в тексте исключения провайдера рерайта.
_BILLING_MARKERS = ("недостаточно средств", "insufficient", "quota", "billing", "баланс")


def is_billing_error(exc: BaseException) -> bool:
    """Ошибка оплаты/баланса у провайдера рерайта (HTTP 402 или текст про
    нехватку средств). Такая ошибка постоянна: она одинаково валит КАЖДЫЙ
    пост, и продолжать пачку бессмысленно — только сожжём всю очередь в
    failed, которую потом руками разгребать. Лучше остановиться и оставить
    посты `new` до пополнения счёта. Живёт здесь (а не в scheduler/jobs.py),
    чтобы и editorial-цикл мог отличить 402 от обычного сбоя без импорта
    планировщика (иначе цикл jobs→editorial→jobs)."""
    if getattr(exc, "status_code", None) == 402:
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _BILLING_MARKERS)

# Имя настройки с текстом промпта для каждого стиль-профиля (F15). Раньше поле
# было только у "default", а остальные стили читались прямо из файлов —
# источник со `style_profile="news"` молча игнорировал промпт, отредактированный
# в админке. Теперь редактируются все; файл `prompts/<стиль>.txt` остаётся
# запасным вариантом, если поле очистили пустым.
#
# Порядок ключей = порядок в выпадающем списке стилей на /sources/{id}.
_STYLE_SETTING_FIELDS = {
    "default": "rewrite_prompt_template",
    "news": "rewrite_prompt_news",
    "opinion": "rewrite_prompt_opinion",
    "instruction": "rewrite_prompt_instruction",
    "humor": "rewrite_prompt_humor",
}

# Известные стиль-профили рерайта (F15). default — нейтральный. Выводится из
# карты выше, а не отдельным литералом: иначе стиль, добавленный только в один
# из двух списков, снова появился бы в UI с нередактируемым промптом.
KNOWN_STYLES = tuple(_STYLE_SETTING_FIELDS)

# Температура по стиль-профилю. Пусто в настройке = общая
# `rewrite_temperature`. У `default` своей нет намеренно: он и есть «общий».
_STYLE_TEMPERATURE_FIELDS = {
    "news": "rewrite_temperature_news",
    "opinion": "rewrite_temperature_opinion",
    "instruction": "rewrite_temperature_instruction",
    "humor": "rewrite_temperature_humor",
}


def temperature_for_style(prompt_name: str) -> float:
    """Какая температура обслуживает стиль-профиль.

    ЗАЧЕМ ОТДЕЛЬНО ПО ПРОФИЛЯМ. Одна температура на все — источник
    выдуманных фактов в новостях: при 0.8 модель дописала в новость число,
    которого в источнике нет, хотя промпт это прямо запрещает. Новость и
    инструкция живут фактами, мнение и юмор без свободы становятся
    пресными — одним числом это не выражается.
    """
    settings = get_settings()
    field = _STYLE_TEMPERATURE_FIELDS.get(prompt_name)
    if field is not None:
        own = getattr(settings, field, None)
        if own is not None:
            return float(own)
    return settings.rewrite_temperature

# Промпты, которые НЕ являются стиль-профилями и потому в KNOWN_STYLES не
# входят (иначе «article» появился бы в выпадающем списке стилей источника,
# хотя это другая ось: стиль — как писать, формат — куда публиковать).
# editor/journalist_revise — служебные промпты редакции из двух агентов
# (F40, см. rewriter/editorial.py), тоже не стили: их формат другой и они
# не выбираются на источнике.
_EXTRA_PROMPT_FIELDS = {
    "article": "article_prompt_template",
    "editor": "editorial_prompt_template",
    "journalist_revise": "editorial_revise_prompt_template",
    # F43: составитель викторины — тоже не стиль, отдельная ось.
    "quiz": "quiz_prompt_template",
}

# Повторяется последней строкой промпта, когда анти-ИИ блок отодвинул секцию
# «ОТВЕТ» шаблона от конца (см. `build_rewrite_prompt`).
_OUTPUT_CONTRACT = (
    "Ещё раз: верни только готовый текст, без вступлений и пояснений."
)


# Роли, у которых может быть своя модель (см. `Settings.openai_model_*`).
# Пустое переопределение означает «основная модель».
ROLE_MAIN = "main"
ROLE_EDITOR = "editor"
ROLE_QUIZ = "quiz"
ROLE_AUX = "aux"


def model_for_role(role: str = ROLE_MAIN) -> str:
    """Какая модель обслуживает роль. Читается НА КАЖДЫЙ ВЫЗОВ.

    Не в конструкторе клиента: тогда смена модели в админке применялась бы
    только после пересборки клиента, а поле обещает «применяется сразу».
    Температура читается здесь же по тому же принципу.
    """
    settings = get_settings()
    override = {
        ROLE_EDITOR: settings.openai_model_editor,
        ROLE_QUIZ: settings.openai_model_quiz,
        ROLE_AUX: settings.openai_model_aux,
    }.get(role, "")
    return override.strip() or settings.openai_model


@dataclass
class RewriteResult:
    """Результат рерайта: текст и метрики токенов."""

    text: str
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@lru_cache
def load_prompt(name: str = "default") -> str:
    """Загрузить промпт-шаблон по имени (без расширения)."""
    path = _PROMPTS_DIR / f"{name}.txt"
    return path.read_text(encoding="utf-8")


def prompt_exists(name: str) -> bool:
    """Есть ли файл промпта с таким именем."""
    return bool(name) and (_PROMPTS_DIR / f"{name}.txt").exists()


def resolve_style_prompt(style: str | None) -> str:
    """Выбрать имя промпта по стилю источника (F15).

    Берём стиль источника; если он пуст или для него нет файла — профиль по
    умолчанию из настроек; если и его нет — `default`.
    """
    settings = get_settings()
    for candidate in (style, settings.default_style_profile):
        if candidate and prompt_exists(candidate):
            return candidate
    return "default"


def resolve_rewrite_template(prompt_name: str) -> str:
    """Выбрать шаблон промпта для `RewriterClient.rewrite()`.

    Приоритет: настройка из `/settings` → одноимённый файл `prompts/*.txt`.
    Стиль, которого нет ни в настройках, ни среди файлов, — не ошибка на
    этом уровне: `resolve_style_prompt()` выше уже отфильтровал такие имена.
    """
    field = _STYLE_SETTING_FIELDS.get(prompt_name) or _EXTRA_PROMPT_FIELDS.get(prompt_name)
    if field:
        configured = str(getattr(get_settings(), field, "")).strip()
        if configured:
            return configured
    return load_prompt(prompt_name)


def build_rewrite_prompt(
    prompt_name: str, post_text: str, link_content: str = "",
    language: str | None = None,
) -> str:
    """Собрать финальный промпт: шаблон стиля + анти-ИИ блок + язык.

    Анти-ИИ блок (`rewrite_humanize_instructions`) добавляется ОДИН на все
    стили и ПОСЛЕ шаблона — инструкции в конце промпта модель соблюдает
    заметно охотнее, чем закопанные в середину, а держать пять копий одного
    и того же правила в пяти шаблонах означало бы гарантированно разъехавшиеся
    редакции.

    `language` — код языка целевой группы (см. `tg_repost/languages.py`).
    None означает «не указывать язык вовсе»: модель ответит на языке
    исходника, как было до появления языка у целей. Указание ставится САМЫМ
    последним, после анти-ИИ блока: получив материал на одном языке, модель
    по умолчанию отвечает на нём же, и требование сменить язык должно быть
    последним, что она читает.
    """
    template = resolve_rewrite_template(prompt_name)
    prompt = template.format(post_text=post_text, link_content=link_content)

    settings = get_settings()
    if settings.rewrite_humanize_enabled:
        humanize = settings.rewrite_humanize_instructions.strip()
        if humanize:
            # Анти-ИИ блок отодвигает секцию «ОТВЕТ» шаблона из конца в
            # середину, а именно последняя строка соблюдается охотнее всего.
            # Поэтому контракт ответа повторяется после него одной строкой —
            # иначе модель начинает предварять пост фразами вроде «Вот
            # переписанный текст». Добавляется ТОЛЬКО вместе с блоком: без
            # него «ОТВЕТ» и так стоит последним, и дублировать нечего.
            prompt = f"{prompt}\n\n{humanize}\n\n{_OUTPUT_CONTRACT}"
    if language is not None:
        prompt = f"{prompt}\n\n{languages.instruction(language)}"
    return prompt


class RewriterClient:
    """Асинхронный клиент рерайта/эмбеддингов."""

    def __init__(self) -> None:
        settings = get_settings()
        # Прокси для рерайт-нейросети (единый прокси-раздел, галочка
        # «использовать для нейросети рерайта», см. tg_repost/proxy.py). Свой
        # http_client — единственный способ прогнать OpenAI-SDK через прокси.
        proxy_url = proxy_module.httpx_proxy_url(settings, "rewrite")
        http_client = (
            httpx.AsyncClient(proxy=proxy_url, timeout=settings.openai_timeout_seconds)
            if proxy_url else None
        )
        self._client = AsyncOpenAI(
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            # Явный таймаут вместо дефолтного: рерайт по ПОЛНОЙ статье (F16)
            # — это длинный промпт, и на медленной модели запрос упирался в
            # дефолт, пост уходил в failed с «Request timed out» (найдено на
            # RSS-лентах Ubuntu USN). Значение правится в /settings.
            timeout=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
            http_client=http_client,
        )
        # Только для сообщений в лог: сам вызов берёт модель через
        # `model_for_role()`, иначе смена модели в админке ждала бы
        # пересборки клиента.
        self._model = settings.openai_model
        self._embedding_model = settings.openai_embedding_model

    async def rewrite(
        self, post_text: str, prompt_name: str = "default", link_content: str = "",
        language: str | None = None,
    ) -> RewriteResult:
        """Переписать текст поста выбранным стиль-профилем (F06/F15).

        `link_content` — текст статьи по ссылке из поста (F16-доп., см.
        `enrichment/link_content.py`), пусто — если ссылки не было или
        переход не удался, тогда рерайт идёт только по `post_text`, как
        раньше.

        `language` — язык готового поста (код из `tg_repost/languages.py`),
        берётся у ЦЕЛЕВОЙ группы. None — не указывать язык вовсе, модель
        ответит на языке исходника (поведение до появления языка у целей).
        """
        prompt = build_rewrite_prompt(prompt_name, post_text, link_content, language)
        # Настройки читаются на КАЖДЫЙ вызов, а не кэшируются в __init__:
        # температура и промпты правятся в /settings живьём, без пересборки
        # клиента (в отличие от base_url/api_key/модели — те в конструкторе
        # AsyncOpenAI, поэтому требуют resync, см. get_rewriter()).
        temperature = temperature_for_style(prompt_name)

        logger.debug(
            "Запрос рерайта: model=%s, стиль=%s, язык=%s, длина=%d, ссылка=%s, t=%.2f",
            self._model, prompt_name, language or "исходный", len(post_text),
            bool(link_content), temperature,
        )

        response = await self._client.chat.completions.create(
            model=model_for_role(ROLE_MAIN),
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )

        text = (response.choices[0].message.content or "").strip()
        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0

        logger.info(
            "Рерайт готов (стиль=%s): токены prompt=%d completion=%d",
            prompt_name, prompt_tokens, completion_tokens,
        )
        return RewriteResult(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    async def rewrite_with_prompt(
        self, prompt: str, *, temperature: float | None = None,
        role: str = ROLE_MAIN,
    ) -> RewriteResult:
        """Рерайт по УЖЕ собранному промпту (формат «статья», см.
        `telegraph/article.py`; рецензия/правка редакции, см.
        `rewriter/editorial.py`). Отдельный метод, потому что `rewrite()`
        собирает промпт сам из стиль-профиля, а тут шаблон и сборка — на
        стороне вызывающего.

        `temperature=None` — брать `rewrite_temperature` из настроек (прежнее
        поведение). Явное значение нужно рецензии редактора: фактчек должен
        быть детерминированным, а не «творческим» на 0.8.

        `role` — чья это работа. У редактора и у квизов может стоять своя
        модель (`/settings`), пустое поле означает основную. Статья на
        Telegraph роли не имеет намеренно: это тот же пост, только длиннее, и
        отдавать его модели попроще значило бы ухудшить главный материал."""
        temperature = (
            temperature if temperature is not None else get_settings().rewrite_temperature
        )
        response = await self._client.chat.completions.create(
            model=model_for_role(role),
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        text = (response.choices[0].message.content or "").strip()
        usage = response.usage
        return RewriteResult(
            text=text,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
        )

    async def complete(self, prompt: str, *, temperature: float = 0.3) -> str:
        """Одноразовый LLM-вызов для вспомогательных задач. Возвращает текст.

        Через этот метод идут ВСЕ мелкие поручения: ключевые слова и отбор
        источников (F16), текст нативной рекламы (F21), запрос для генератора
        обложки, сводка дайджеста (F20). Роль у них общая — `aux`, и модель
        для неё задаётся одним полем: разводить их по четырём настройкам
        значило бы четыре поля ради задач на десяток токенов каждая.
        """
        response = await self._client.chat.completions.create(
            model=model_for_role(ROLE_AUX),
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        return (response.choices[0].message.content or "").strip()

    async def embed(self, text: str) -> list[float]:
        """Получить эмбеддинг текста (F13). Бросает исключение при ошибке API."""
        response = await self._client.embeddings.create(
            model=self._embedding_model,
            input=text,
        )
        return list(response.data[0].embedding)


@lru_cache
def get_rewriter() -> RewriterClient:
    """Кэшированный синглтон клиента рерайта/эмбеддингов — используется
    ТОЛЬКО `telegram/listener.py` для эмбеддингов дедупа (F13) при захвате
    сообщения. Не путать с `webui.supervisor._components.rewriter` —
    отдельный, независимо пересобираемый экземпляр для pipeline_tick/
    digest_job. Два разных кэша одного и того же класса: `_sync_jobs()`
    пересобирает `_components.rewriter`, но НЕ трогает этот — без явного
    `invalidate_rewriter_cache()` эмбеддинги в listener.py продолжали бы
    работать со старым base_url/моделью бесконечно, даже после resync
    (найдено на реальном деплое: смена модели рерайта применилась к
    pipeline_tick, а "Не удалось получить эмбеддинг" в listener.py — нет)."""
    return RewriterClient()


def invalidate_rewriter_cache() -> None:
    """Сбросить кэш `get_rewriter()` — вызывать вместе с пересборкой
    `_components.rewriter` (см. `webui/supervisor.py::_sync_jobs`)."""
    get_rewriter.cache_clear()
