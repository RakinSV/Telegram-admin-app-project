"""«Редакционная кухня» — трансляция диалога агентов в Telegram-чат (F50).

Журналист и редактор — не отдельные боты, а LLM-роли внутри одного процесса
(см. `rewriter/editorial.py`): они не переписываются, а вызываются
последовательно. Этот модуль показывает их обмен так, как будто это живой
разговор — цепочкой сообщений, связанных реплаями.

Зачем: когда рерайт выходит плохим, по одному результату не понять, где
сломалось — статья не скачалась, редактор придрался не к тому, промпт кривой.
Живой ход показывает конкретный шаг, и чинится конкретная причина.

Отдельный бот НЕ нужен: шлёт существующий репост-бот. Ошибка отправки никогда
не влияет на рерайт (см. `editorial._emit`) — это диагностика, а не пайплайн.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aiogram import Bot

from tg_repost.config import get_settings
from tg_repost.logging_conf import get_logger, sanitize_proxy_error
from tg_repost.rewriter.editorial import (
    STEP_DRAFT,
    STEP_REVIEW,
    STEP_REVISION,
    STEP_VERDICT,
    STEP_WEB_FINDINGS,
    StepCallback,
)
from tg_repost.telegram.text_utils import clip, tg_len

logger = get_logger(__name__)

# Лимит одного сообщения Telegram — 4096 единиц UTF-16. Оставляем запас под
# заголовок стадии и многоточие обрезки.
_MESSAGE_LIMIT = 4096
_BODY_BUDGET = 3800

# Подпись каждой стадии: эмодзи + человеческое название. Порядок словаря = тот
# порядок, в котором стадии реально приходят из editorial.py.
_STAGE_TITLES: dict[str, str] = {
    STEP_DRAFT: "📝 Журналист · черновик",
    STEP_REVIEW: "🔍 Редактор · замечания",
    STEP_WEB_FINDINGS: "🌐 Проверка фактов",
    STEP_REVISION: "✍️ Журналист · правка",
    STEP_VERDICT: "✅ Редактор · вердикт",
}

# Режимы многословности. `problems` — по умолчанию: молчит, когда редактор всем
# доволен, и показывает разбор, только если он реально к чему-то придрался.
# Иначе пачка из 5 постов за тик даёт ~25 сообщений.
VERBOSITY_ALL = "all"
VERBOSITY_PROBLEMS = "problems"
VERBOSITY_SUMMARY = "summary"
VERBOSITY_CHOICES = (VERBOSITY_ALL, VERBOSITY_PROBLEMS, VERBOSITY_SUMMARY)


@dataclass
class _ThreadState:
    """Состояние цепочки ОДНОГО поста.

    `root_id` — сообщение, к которому реплаятся остальные (в чате это выглядит
    веткой обсуждения). `pending` — придержанный черновик для режима
    `problems`: на момент его появления ещё неизвестно, придерётся ли редактор,
    поэтому показываем задним числом и только если придрался.
    """

    root_id: int | None = None
    pending: list[tuple[str, str]] = field(default_factory=list)
    had_problems: bool = False


def build_newsroom_callback(
    bot: Bot, post_id: int,
) -> StepCallback | None:
    """Собрать callback трансляции для ОДНОГО поста, либо None если выключено.

    None (а не пустышка) — чтобы `editorial_rewrite` вообще не тратил вызовы,
    когда трансляция не нужна.
    """
    settings = get_settings()
    if not settings.editorial_newsroom_enabled:
        return None
    chat_id = settings.editorial_newsroom_chat_id
    if not chat_id:
        return None

    verbosity = settings.editorial_newsroom_verbosity
    if verbosity not in VERBOSITY_CHOICES:
        verbosity = VERBOSITY_PROBLEMS

    state = _ThreadState()

    async def _send(stage: str, text: str) -> None:
        if verbosity == VERBOSITY_SUMMARY and stage != STEP_VERDICT:
            return
        if verbosity == VERBOSITY_PROBLEMS:
            if stage == STEP_DRAFT:
                # Ещё не знаем, будут ли замечания — придержим до рецензии.
                state.pending.append((stage, text))
                return
            if stage == STEP_VERDICT and not state.had_problems:
                # Редактор одобрил сразу: показывать нечего, молчим.
                return
            if stage == STEP_REVIEW:
                state.had_problems = True
            # Пошли замечания — сначала выливаем придержанный черновик.
            held, state.pending = state.pending, []
            for held_stage, held_text in held:
                await _deliver(bot, chat_id, post_id, held_stage, held_text, state)
        await _deliver(bot, chat_id, post_id, stage, text, state)

    return _send


def _format(post_id: int, stage: str, text: str) -> str:
    """Заголовок стадии + тело, обрезанное под лимит Telegram."""
    title = _STAGE_TITLES.get(stage, stage)
    header = f"{title} · пост #{post_id}\n"
    budget = min(_BODY_BUDGET, _MESSAGE_LIMIT - tg_len(header) - 1)
    body = clip(text.strip(), budget)
    if tg_len(text.strip()) > budget:
        body += "…"
    return f"{header}{body}"


async def _deliver(
    bot: Bot, chat_id: int, post_id: int,
    stage: str, text: str, state: _ThreadState,
) -> None:
    """Отправить одно сообщение цепочки. Первое становится корнем, остальные
    реплаятся к нему — в чате это выглядит как ветка обсуждения."""
    try:
        message = await bot.send_message(
            chat_id=chat_id,
            text=_format(post_id, stage, text),
            # Никакого parse_mode: в текстах агентов бывают <, > и *, а
            # ломать трансляцию из-за разметки — последнее, чего мы хотим от
            # диагностического инструмента.
            parse_mode=None,
            reply_to_message_id=state.root_id,
            disable_notification=True,  # кухня не должна пиликать на каждый шаг
        )
    except Exception as exc:  # noqa: BLE001
        # sanitize_proxy_error — трансляция ходит через тот же прокси, что и
        # бот, и текст ошибки подключения может содержать логин:пароль.
        logger.warning(
            "Не удалось отправить шаг '%s' поста %s в редакционную кухню: %s",
            stage, post_id, sanitize_proxy_error(str(exc)),
        )
        return
    if state.root_id is None:
        state.root_id = message.message_id
