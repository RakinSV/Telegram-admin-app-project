"""Команды администратора (G07) — только для admin/creator группы, проверка
через `bot.get_chat_administrators` с коротким TTL-кэшем (см. `_get_admin_ids`
ниже) — не персистентный список, живёт только в памяти процесса.

Bot API не даёт надёжно резолвить @username произвольного пользователя в
user_id (работает только для контактов бота/публичных сущностей) — поэтому,
как и у большинства модераторских ботов, цель команды берётся ИЗ ОТВЕТА на
сообщение пользователя (`message.reply_to_message`), либо, если ответа нет
(например пользователь уже забанен и его сообщений не видно), из числового
user_id первым аргументом: `/ban 123456789 причина`.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import ChatPermissions, Message

from guardian import domains_repo, settings_store, stopwords_repo, trusted_repo
from guardian.config import get_guardian_settings
from guardian.db.models import Member, ModerationLog, Warning
from guardian.db.session import session_scope
from guardian.handlers import messages as messages_handlers
from guardian.logging_conf import get_logger
from guardian.services.log_channel import log_action
from guardian.services.warn_system import add_warn

logger = get_logger(__name__)
router = Router(name="admin")

_DURATION_RE = re.compile(r"^(\d+)([mhd])$", re.IGNORECASE)
_DURATION_UNITS = {"m": "minutes", "h": "hours", "d": "days"}
# Telegram отклоняет/нормализует ограничения дольше 366 дней (фактически
# трактует как "навсегда") — клэмпим сами, чтобы не полагаться на то, как
# именно API обработает переполнение, и не пугать админа сырой ошибкой API
# на банальную опечатку в длительности (найдено при код-ревью).
_MAX_MUTE_DURATION = timedelta(days=366)


def _parse_duration(text: str) -> timedelta | None:
    match = _DURATION_RE.match(text.strip())
    if not match:
        return None
    amount, unit = int(match.group(1)), match.group(2).lower()
    duration = timedelta(**{_DURATION_UNITS[unit]: amount})
    return min(duration, _MAX_MUTE_DURATION)


def _resolve_target(message: Message, args: str) -> tuple[int | None, str]:
    """Вернуть (user_id, оставшиеся_аргументы)."""
    if (
        message.reply_to_message is not None
        and message.reply_to_message.from_user is not None
    ):
        return message.reply_to_message.from_user.id, args.strip()
    parts = args.split(maxsplit=1)
    if parts and parts[0].lstrip("-").isdigit():
        return int(parts[0]), (parts[1] if len(parts) > 1 else "")
    return None, args


# Кэш id админов группы (TTL, не персистентный) — раньше каждая команда (в
# т.ч. от НЕ-админа, до отказа) дёргала `get_chat_member` живьём, что даёт
# любому участнику дешёвый способ засыпать Bot API запросами, просто спамя
# любую /-команду (найдено при security-аудите). `get_chat_administrators`
# возвращает весь список админов ОДНИМ вызовом — на порядки дешевле per-user
# `get_chat_member`, вызываемого на каждую команду каждого участника.
# TTL — компромисс между "не долбить API" и "снятые права админа должны
# перестать работать не мгновенно, а в течение TTL", разумно для чата с
# нечастой сменой модераторов.
_ADMIN_CACHE_TTL_SECONDS = 60
_admin_cache: dict[int, tuple[set[int], float]] = {}


async def _get_admin_ids(bot: Bot, chat_id: int) -> set[int]:
    cached = _admin_cache.get(chat_id)
    now = time.monotonic()
    if cached is not None and now - cached[1] < _ADMIN_CACHE_TTL_SECONDS:
        return cached[0]
    try:
        admins = await bot.get_chat_administrators(chat_id)
    except TelegramBadRequest:
        return cached[0] if cached is not None else set()
    ids = {admin.user.id for admin in admins}
    _admin_cache[chat_id] = (ids, now)
    return ids


async def _is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    return user_id in await _get_admin_ids(bot, chat_id)


async def _require_admin(message: Message, bot: Bot) -> int | None:
    """Вернуть id вызвавшего команду администратора, либо None (и ответить
    отказом) — возврат id вместо bool даёт mypy статически знать, что
    `message.from_user` не None в остальном теле команды, не полагаясь на
    ручной `str(message.from_user.id)` в каждом обработчике."""
    if message.from_user is None or not await _is_admin(
        bot, message.chat.id, message.from_user.id
    ):
        await message.reply("Команда доступна только администраторам группы.")
        return None
    return message.from_user.id


def _reload_keyword_filter() -> None:
    with session_scope() as session:
        messages_handlers.keyword_filter.reload(session)


def _reload_link_filter() -> None:
    with session_scope() as session:
        messages_handlers.link_filter.reload(session)


@router.message(Command("warn"))
async def cmd_warn(message: Message, command: CommandObject, bot: Bot) -> None:
    actor_id = await _require_admin(message, bot)
    if actor_id is None:
        return
    user_id, reason = _resolve_target(message, command.args or "")
    if user_id is None:
        await message.reply(
            "Использование: ответь на сообщение пользователя командой /warn [причина]"
        )
        return
    warn_count = await add_warn(
        bot,
        user_id,
        message.chat.id,
        reason or "варн от администратора",
        issued_by=str(actor_id),
    )
    await message.reply(f"Варн выдан. Текущий счётчик: {warn_count}.")


@router.message(Command("mute"))
async def cmd_mute(message: Message, command: CommandObject, bot: Bot) -> None:
    actor_id = await _require_admin(message, bot)
    if actor_id is None:
        return
    user_id, rest = _resolve_target(message, command.args or "")
    if user_id is None:
        await message.reply(
            "Использование: ответь на сообщение пользователя командой /mute [1h|30m|2d]"
        )
        return
    settings = get_guardian_settings()
    duration = _parse_duration(rest.split(maxsplit=1)[0]) if rest else None
    if duration is None:
        duration = timedelta(hours=settings.mute_duration_hours)
    until = datetime.now(timezone.utc) + duration
    try:
        await bot.restrict_chat_member(
            message.chat.id,
            user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
    except TelegramBadRequest as exc:
        await message.reply(f"Не удалось замутить: {exc}")
        return
    with session_scope() as session:
        session.add(
            ModerationLog(
                action="mute",
                user_id=user_id,
                chat_id=message.chat.id,
                actor=str(actor_id),
            )
        )
    await log_action(
        bot,
        "mute",
        user_id=user_id,
        chat_id=message.chat.id,
        reason=f"вручную, до {until:%H:%M UTC}",
    )
    await message.reply(f"Замучен до {until:%H:%M UTC}.")


@router.message(Command("unmute"))
async def cmd_unmute(message: Message, command: CommandObject, bot: Bot) -> None:
    actor_id = await _require_admin(message, bot)
    if actor_id is None:
        return
    user_id, _rest = _resolve_target(message, command.args or "")
    if user_id is None:
        await message.reply(
            "Использование: ответь на сообщение пользователя командой /unmute"
        )
        return
    chat = await bot.get_chat(message.chat.id)
    try:
        await bot.restrict_chat_member(
            message.chat.id,
            user_id,
            permissions=chat.permissions or ChatPermissions(can_send_messages=True),
        )
    except TelegramBadRequest as exc:
        await message.reply(f"Не удалось размутить: {exc}")
        return
    with session_scope() as session:
        session.add(
            ModerationLog(
                action="unmute",
                user_id=user_id,
                chat_id=message.chat.id,
                actor=str(actor_id),
            )
        )
    await log_action(
        bot, "unmute", user_id=user_id, chat_id=message.chat.id, reason="вручную"
    )
    await message.reply("Размучен.")


@router.message(Command("ban"))
async def cmd_ban(message: Message, command: CommandObject, bot: Bot) -> None:
    actor_id = await _require_admin(message, bot)
    if actor_id is None:
        return
    user_id, reason = _resolve_target(message, command.args or "")
    if user_id is None:
        await message.reply(
            "Использование: ответь на сообщение пользователя командой /ban [причина]"
        )
        return
    try:
        await bot.ban_chat_member(message.chat.id, user_id)
    except TelegramBadRequest as exc:
        await message.reply(f"Не удалось забанить: {exc}")
        return
    with session_scope() as session:
        member = (
            session.query(Member)
            .filter(Member.user_id == user_id, Member.chat_id == message.chat.id)
            .one_or_none()
        )
        if member is not None:
            member.is_banned = True
        session.add(
            ModerationLog(
                action="ban",
                user_id=user_id,
                chat_id=message.chat.id,
                reason=reason or None,
                actor=str(actor_id),
            )
        )
    await log_action(
        bot, "ban", user_id=user_id, chat_id=message.chat.id, reason=reason or "вручную"
    )
    await message.reply("Забанен.")


@router.message(Command("unban"))
async def cmd_unban(message: Message, command: CommandObject, bot: Bot) -> None:
    actor_id = await _require_admin(message, bot)
    if actor_id is None:
        return
    user_id, _rest = _resolve_target(message, command.args or "")
    if user_id is None:
        await message.reply("Использование: /unban <user_id>")
        return
    try:
        await bot.unban_chat_member(message.chat.id, user_id, only_if_banned=True)
    except TelegramBadRequest as exc:
        await message.reply(f"Не удалось разбанить: {exc}")
        return
    with session_scope() as session:
        member = (
            session.query(Member)
            .filter(Member.user_id == user_id, Member.chat_id == message.chat.id)
            .one_or_none()
        )
        if member is not None:
            member.is_banned = False
        session.add(
            ModerationLog(
                action="unban",
                user_id=user_id,
                chat_id=message.chat.id,
                actor=str(actor_id),
            )
        )
    await log_action(
        bot, "unban", user_id=user_id, chat_id=message.chat.id, reason="вручную"
    )
    await message.reply("Разбанен.")


@router.message(Command("kick"))
async def cmd_kick(message: Message, command: CommandObject, bot: Bot) -> None:
    actor_id = await _require_admin(message, bot)
    if actor_id is None:
        return
    user_id, reason = _resolve_target(message, command.args or "")
    if user_id is None:
        await message.reply(
            "Использование: ответь на сообщение пользователя командой /kick [причина]"
        )
        return
    try:
        await bot.ban_chat_member(message.chat.id, user_id)
        await bot.unban_chat_member(message.chat.id, user_id, only_if_banned=True)
    except TelegramBadRequest as exc:
        await message.reply(f"Не удалось кикнуть: {exc}")
        return
    with session_scope() as session:
        session.add(
            ModerationLog(
                action="kick",
                user_id=user_id,
                chat_id=message.chat.id,
                reason=reason or None,
                actor=str(actor_id),
            )
        )
    await log_action(
        bot,
        "kick",
        user_id=user_id,
        chat_id=message.chat.id,
        reason=reason or "вручную",
    )
    await message.reply("Кикнут (может зайти снова).")


@router.message(Command("check"))
async def cmd_check(message: Message, command: CommandObject, bot: Bot) -> None:
    actor_id = await _require_admin(message, bot)
    if actor_id is None:
        return
    user_id, _rest = _resolve_target(message, command.args or "")
    if user_id is None:
        await message.reply(
            "Использование: ответь на сообщение пользователя командой /check"
        )
        return
    with session_scope() as session:
        member = (
            session.query(Member)
            .filter(Member.user_id == user_id, Member.chat_id == message.chat.id)
            .one_or_none()
        )
        recent_warns = (
            session.query(Warning)
            .filter(Warning.user_id == user_id, Warning.chat_id == message.chat.id)
            .order_by(Warning.created_at.desc())
            .limit(5)
            .all()
        )
        lines = [f"Пользователь id{user_id}:"]
        if member is None:
            lines.append("нет записей.")
        else:
            lines.append(
                f"варнов: {member.warn_count}, забанен: {'да' if member.is_banned else 'нет'}, "
                f"доверенный: {'да' if member.is_trusted else 'нет'}"
            )
        if recent_warns:
            lines.append("Последние варны:")
            lines.extend(
                f"• {w.created_at:%Y-%m-%d %H:%M} — {w.reason}" for w in recent_warns
            )
    await message.reply("\n".join(lines))


@router.message(Command("addword"))
async def cmd_addword(message: Message, command: CommandObject, bot: Bot) -> None:
    actor_id = await _require_admin(message, bot)
    if actor_id is None:
        return
    word = (command.args or "").strip().lower()
    if not word:
        await message.reply("Использование: /addword <слово или фраза>")
        return
    added = stopwords_repo.add_stopword(word, message.chat.id, added_by=str(actor_id))
    _reload_keyword_filter()
    await message.reply(
        f"Стоп-слово «{word}» добавлено."
        if added
        else f"Стоп-слово «{word}» уже было в списке."
    )


@router.message(Command("delword"))
async def cmd_delword(message: Message, command: CommandObject, bot: Bot) -> None:
    actor_id = await _require_admin(message, bot)
    if actor_id is None:
        return
    word = (command.args or "").strip().lower()
    if not word:
        await message.reply("Использование: /delword <слово или фраза>")
        return
    stopwords_repo.remove_stopword(word, message.chat.id)
    _reload_keyword_filter()
    await message.reply(f"Стоп-слово «{word}» удалено (если было).")


@router.message(Command("listwords"))
async def cmd_listwords(message: Message, bot: Bot) -> None:
    if await _require_admin(message, bot) is None:
        return
    words = stopwords_repo.list_stopwords(message.chat.id)
    await message.reply("Стоп-слова:\n" + ("\n".join(words) if words else "(пусто)"))


@router.message(Command("trust"))
async def cmd_trust(message: Message, command: CommandObject, bot: Bot) -> None:
    actor_id = await _require_admin(message, bot)
    if actor_id is None:
        return
    user_id, reason = _resolve_target(message, command.args or "")
    if user_id is None:
        await message.reply(
            "Использование: ответь на сообщение пользователя командой /trust [причина]"
        )
        return
    added = trusted_repo.add_trusted(
        user_id, message.chat.id, str(actor_id), reason or None
    )
    if added:
        await log_action(
            bot,
            "trust",
            user_id=user_id,
            chat_id=message.chat.id,
            reason=reason or "вручную",
        )
    await message.reply("Добавлен в доверенные." if added else "Уже был доверенным.")


@router.message(Command("untrust"))
async def cmd_untrust(message: Message, command: CommandObject, bot: Bot) -> None:
    actor_id = await _require_admin(message, bot)
    if actor_id is None:
        return
    user_id, _rest = _resolve_target(message, command.args or "")
    if user_id is None:
        await message.reply(
            "Использование: ответь на сообщение пользователя командой /untrust"
        )
        return
    removed = trusted_repo.remove_trusted(user_id, message.chat.id, str(actor_id))
    if removed:
        await log_action(
            bot, "untrust", user_id=user_id, chat_id=message.chat.id, reason="вручную"
        )
    await message.reply("Убран из доверенных." if removed else "Не был доверенным.")


@router.message(Command("addomain"))
async def cmd_addomain(message: Message, command: CommandObject, bot: Bot) -> None:
    actor_id = await _require_admin(message, bot)
    if actor_id is None:
        return
    raw_domain = (command.args or "").strip()
    if not raw_domain:
        await message.reply("Использование: /addomain <домен>")
        return
    domain = domains_repo.add_allowed_domain(raw_domain, message.chat.id, str(actor_id))
    if not domain:
        await message.reply(
            "Пустой домен (например, только «www.») — нечего добавлять."
        )
        return
    _reload_link_filter()
    await message.reply(f"Домен «{domain}» добавлен в whitelist.")


@router.message(Command("deldomain"))
async def cmd_deldomain(message: Message, command: CommandObject, bot: Bot) -> None:
    actor_id = await _require_admin(message, bot)
    if actor_id is None:
        return
    raw_domain = (command.args or "").strip()
    if not raw_domain:
        await message.reply("Использование: /deldomain <домен>")
        return
    domains_repo.remove_allowed_domain(raw_domain, message.chat.id, str(actor_id))
    _reload_link_filter()
    await message.reply(f"Домен «{raw_domain}» удалён из whitelist (если был).")


@router.message(Command("listdomains"))
async def cmd_listdomains(message: Message, bot: Bot) -> None:
    if await _require_admin(message, bot) is None:
        return
    domains = domains_repo.list_allowed_domains(message.chat.id)
    await message.reply(
        "Whitelist доменов:\n" + ("\n".join(domains) if domains else "(пусто)")
    )


# --- Конфиг через команды (G13) — те же настройки, что и в веб-админке
# tg_repost (`settings_store.save_setting`), альтернативный интерфейс для
# случаев без доступа к веб-панели. Валидация `spam_mode`/`captcha_type`
# берёт allowlist из `settings_store.SETTINGS_GROUPS` (`SettingField.choices`)
# — единый источник истины с веб-формой, не дублирует список значений.


def _find_field(name: str) -> settings_store.SettingField:
    for group in settings_store.SETTINGS_GROUPS:
        for field in group.fields:
            if field.name == name:
                return field
    raise KeyError(name)


@router.message(Command("setmode"))
async def cmd_setmode(message: Message, command: CommandObject, bot: Bot) -> None:
    actor_id = await _require_admin(message, bot)
    if actor_id is None:
        return
    mode = (command.args or "").strip().lower()
    choices = _find_field("spam_mode").choices or ()
    if mode not in choices:
        await message.reply(f"Использование: /setmode {'|'.join(choices)}")
        return
    settings_store.save_setting("spam_mode", mode, "str", updated_by=str(actor_id))
    await message.reply(f"Режим спам-фильтра: {mode}.")


@router.message(Command("setcaptcha"))
async def cmd_setcaptcha(message: Message, command: CommandObject, bot: Bot) -> None:
    actor_id = await _require_admin(message, bot)
    if actor_id is None:
        return
    captcha_type = (command.args or "").strip().lower()
    choices = _find_field("captcha_type").choices or ()
    if captcha_type not in choices:
        await message.reply(f"Использование: /setcaptcha {'|'.join(choices)}")
        return
    settings_store.save_setting("captcha_type", captcha_type, "str", updated_by=str(actor_id))
    await message.reply(f"Тип капчи: {captcha_type}.")


@router.message(Command("setwarn"))
async def cmd_setwarn(message: Message, command: CommandObject, bot: Bot) -> None:
    actor_id = await _require_admin(message, bot)
    if actor_id is None:
        return
    parts = (command.args or "").split()
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        await message.reply(
            "Использование: /setwarn <мут_порог> <кик_порог> <бан_порог> (целые числа)"
        )
        return
    mute_t, kick_t, ban_t = (int(p) for p in parts)
    if not (mute_t < kick_t < ban_t):
        await message.reply("Пороги должны идти по возрастанию: мут < кик < бан.")
        return
    settings_store.save_setting("warn_threshold_mute", mute_t, "int", updated_by=str(actor_id))
    settings_store.save_setting("warn_threshold_kick", kick_t, "int", updated_by=str(actor_id))
    settings_store.save_setting("warn_threshold_ban", ban_t, "int", updated_by=str(actor_id))
    await message.reply(f"Пороги варнов: мут={mute_t}, кик={kick_t}, бан={ban_t}.")


@router.message(Command("setmutime"))
async def cmd_setmutime(message: Message, command: CommandObject, bot: Bot) -> None:
    """Настройка называется `mute_duration_hours` (тот же .env `MUTE_DURATION_HOURS`,
    веб-админка, `/mute`-фолбэк) — команда сохраняет ЧАСЫ, а не минуты, хотя
    первоначальный план (GUARDIAN_FEATURES.md, G13) описывал её как "минуты":
    поле с самого G01 везде по кодовой базе в часах, заводить отдельное
    minutes-поле только под эту команду значило бы либо рассинхрон с
    `/mute`/веб-UI, либо путаницу единиц — текст ответа явно говорит "ч.",
    чтобы не вводить в заблуждение."""
    actor_id = await _require_admin(message, bot)
    if actor_id is None:
        return
    raw = (command.args or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        await message.reply("Использование: /setmutime <часы> (целое положительное число)")
        return
    settings_store.save_setting("mute_duration_hours", int(raw), "int", updated_by=str(actor_id))
    await message.reply(f"Длительность мута по умолчанию: {raw} ч.")


@router.message(Command("mode"))
async def cmd_mode(message: Message, command: CommandObject, bot: Bot) -> None:
    """G16: ручное переключение strict/soft. Если включено расписание тихих
    часов (`quiet_hours_enabled`), следующий тик джобы `bot.py::
    _apply_quiet_hours_schedule` перезапишет это значение согласно текущему
    часу — ручное переключение "держится" только до следующего тика,
    расписание приоритетнее (см. его docstring)."""
    actor_id = await _require_admin(message, bot)
    if actor_id is None:
        return
    mode = (command.args or "").strip().lower()
    if mode not in ("strict", "soft"):
        await message.reply("Использование: /mode strict|soft")
        return
    settings_store.save_setting("strict_mode", mode == "strict", "bool", updated_by=str(actor_id))
    await message.reply(f"Режим строгости: {mode}.")
