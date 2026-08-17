"""Реестр ботов: сколько угодно ботов, все настройки в админке (F75).

МНОГО БОТОВ — ОДИН ПРОЦЕСС. aiogram ведёт несколько ботов одним диспетчером
(`start_polling(*bots)` — «one or more»), и обработчик получает тот бот,
которому пришёл апдейт. Ни отдельных контейнеров, ни вебхуков, ни разводки
апдейтов руками не нужно.

ТОКЕН ШИФРУЕТСЯ МАСТЕР-КЛЮЧОМ АДМИНКИ и наружу не отдаётся НИКОГДА, даже
владельцу: в описание для шаблона он не попадает вовсе — не замаскирован, а
отсутствует. Показать нечего, поэтому пустое поле при правке означает «не
меняли», а не «очистить».

ТОКЕН ПРОВЕРЯЕТСЯ ПРИ СОХРАНЕНИИ, а не при первом запуске. Неверный токен,
принятый молча, оборачивается ботом, который «есть в списке и не работает», и
разбираться в этом владелец будет по логам. Заодно из `getMe` берётся
@username: помнить, какому боту принадлежит строка токена, человек не обязан.

ИМЯ БОТА УНИКАЛЬНО ПО @USERNAME. Один и тот же бот, добавленный дважды, — это
два опроса одного апдейта и двойные ответы человеку.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from tg_repost.db.models import Flow, ManagedBot
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

# Минимальная длина, при которой строку вообще стоит считать токеном:
# формат Telegram — «<цифры>:<буквы и цифры>».
_MIN_TOKEN_LENGTH = 20


class InvalidBot(ValueError):
    """Бот не прошёл проверку."""


@dataclass(frozen=True)
class BotView:
    """Описание бота БЕЗ токена — намеренно.

    Поля для токена здесь нет вовсе: то, чего нет в объекте, невозможно
    случайно вывести в шаблон.
    """

    id: int
    name: str
    username: str | None
    token_hint: str
    is_active: bool
    last_error: str | None
    flows_count: int
    created_at: datetime


def _view(row: ManagedBot, flows_count: int = 0) -> BotView:
    return BotView(
        id=row.id, name=row.name, username=row.username,
        token_hint=row.token_hint, is_active=row.is_active,
        last_error=row.last_error, flows_count=flows_count,
        created_at=row.created_at,
    )


def _master_key() -> str:
    from tg_repost.webui.settings_store import ensure_master_key

    return ensure_master_key()


def _encrypt(token: str) -> tuple[str, str]:
    """Зашифровать токен и сделать маску для показа."""
    from tg_repost.crypto import encrypt

    hint = f"••••{token[-4:]}" if len(token) >= 4 else "••••"
    return encrypt(token, _master_key()), hint


def decrypt_token(bot_id: int) -> str | None:
    """Расшифровать токен — ТОЛЬКО для запуска бота.

    Отдельная функция с говорящим именем, а не поле в `BotView`: так место,
    где токен покидает базу, видно поиском по одному слову.
    """
    from tg_repost.crypto import InvalidToken, decrypt

    with session_scope() as session:
        row = session.get(ManagedBot, bot_id)
        if row is None:
            return None
        try:
            return decrypt(row.token_encrypted, _master_key())
        except InvalidToken:
            logger.error(
                "F75: токен бота «%s» не расшифровывается текущим мастер-ключом",
                row.name,
            )
            return None


async def verify_token(token: str) -> tuple[bool, str]:
    """Спросить у Telegram, чей это токен. `(годен, @username или причина)`.

    Проверка живым вызовом, а не разбором формата: правильно выглядящий, но
    отозванный токен формат проходит, а бота не даёт.
    """
    from aiogram import Bot

    bot = Bot(token=token)
    try:
        me = await bot.get_me()
        return True, me.username or ""
    except Exception as exc:  # noqa: BLE001 — причину показываем владельцу
        return False, str(exc)
    finally:
        await bot.session.close()


async def save(
    name: str,
    token: str,
    *,
    bot_id: int | None = None,
    is_active: bool = False,
) -> int:
    """Добавить бота или обновить существующего.

    Пустой токен при правке означает «не меняли»: показать сохранённый
    невозможно, поэтому трактовать пустоту как очистку значило бы ломать бота
    при каждом переименовании.
    """
    clean_name = name.strip()
    if not clean_name:
        raise InvalidBot("Название бота не может быть пустым")

    clean_token = token.strip()
    username: str | None = None

    if clean_token:
        if len(clean_token) < _MIN_TOKEN_LENGTH or ":" not in clean_token:
            raise InvalidBot("Это не похоже на токен бота — ожидается «цифры:буквы»")
        ok, answer = await verify_token(clean_token)
        if not ok:
            raise InvalidBot(f"Telegram не принял токен: {answer}")
        username = answer
    elif bot_id is None:
        raise InvalidBot("Для нового бота нужен токен")

    with session_scope() as session:
        row = session.get(ManagedBot, bot_id) if bot_id is not None else None
        if row is None and bot_id is not None:
            raise InvalidBot("Бот не найден")

        if username:
            twin = (
                session.query(ManagedBot.id)
                .filter(
                    ManagedBot.username == username,
                    ManagedBot.id != (bot_id or 0),
                )
                .first()
            )
            if twin is not None:
                raise InvalidBot(
                    f"Бот @{username} уже добавлен: два опроса одного апдейта "
                    "означают двойные ответы человеку"
                )

        if row is None:
            row = ManagedBot(name=clean_name, token_encrypted="", token_hint="")
            session.add(row)

        row.name = clean_name
        if clean_token:
            row.token_encrypted, row.token_hint = _encrypt(clean_token)
            row.username = username
            # Новый токен — прежняя ошибка больше не про него.
            row.last_error = None
        row.is_active = is_active
        session.flush()
        logger.info("F75: бот «%s» (@%s) сохранён", clean_name, row.username or "?")
        return row.id


def get(bot_id: int) -> BotView | None:
    with session_scope() as session:
        row = session.get(ManagedBot, bot_id)
        if row is None:
            return None
        count = session.query(Flow.id).filter(Flow.bot_id == bot_id).count()
        return _view(row, count)


def list_all(*, only_active: bool = False) -> list[BotView]:
    with session_scope() as session:
        query = session.query(ManagedBot)
        if only_active:
            query = query.filter(ManagedBot.is_active.is_(True))
        rows = query.order_by(ManagedBot.name.asc()).all()
        return [
            _view(
                row,
                session.query(Flow.id).filter(Flow.bot_id == row.id).count(),
            )
            for row in rows
        ]


def set_active(bot_id: int, active: bool) -> bool:
    with session_scope() as session:
        row = session.get(ManagedBot, bot_id)
        if row is None:
            return False
        row.is_active = active
        return True


def record_error(bot_id: int, error: str) -> None:
    """Запомнить, почему бот не работает.

    Владелец видит «включён» и тишину; без причины на странице он полезет в
    логи контейнера, а это ровно то, от чего админка избавляет.
    """
    with session_scope() as session:
        row = session.get(ManagedBot, bot_id)
        if row is not None:
            row.last_error = error[:255]


def delete(bot_id: int) -> bool:
    """Удалить бота. `False` — нельзя, на нём есть сценарии.

    Сценарий без бота запускать нечем, а прохождения людей внутри него
    ссылаются на узлы: удалить бота значило бы оставить их в пустоте. Убрать
    из работы можно всегда — выключателем.
    """
    with session_scope() as session:
        row = session.get(ManagedBot, bot_id)
        if row is None:
            return False
        has_flows = session.query(Flow.id).filter(Flow.bot_id == bot_id).first()
        if has_flows is not None:
            row.is_active = False
            logger.info(
                "F75: бот #%d не удалён (есть сценарии) — выключен", bot_id,
            )
            return False
        session.delete(row)
        return True
