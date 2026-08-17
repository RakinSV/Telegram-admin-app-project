"""Живые экземпляры ботов реестра (F75).

ОДИН ПРОЦЕСС НА ВСЕ БОТЫ. aiogram ведёт несколько ботов одним диспетчером
(`start_polling(*bots)` — «one or more»), и обработчик получает тот бот,
которому пришёл апдейт. Поэтому здесь только кэш живых экземпляров, а не
пул процессов.

КЭШ ПО `bot_id`, А НЕ ПО ТОКЕНУ. Токен меняют — экземпляр должен пересоздаться;
идентификатор строки при этом остаётся, и по нему легко найти, что выбросить.

СОЗДАНИЕ ЭКЗЕМПЛЯРА НЕ ХОДИТ В СЕТЬ. `Bot(token=...)` только запоминает
строку, поэтому кэш можно наполнять при старте, не рискуя повиснуть на
недоступном Telegram.
"""

from __future__ import annotations

from typing import Any

from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

# bot_id → живой экземпляр. Модульный, потому что боты живут ровно столько,
# сколько процесс: держать их в объекте-владельце значило бы протаскивать его
# через все обработчики.
_instances: dict[int, Any] = {}


def bot_for(bot_id: int) -> Any | None:
    """Живой бот по идентификатору строки реестра.

    `None` — бота нет, он выключен или токен не расшифровывается. Вызывающий
    обязан это проверить: отправлять сообщение нечем, и делать вид, что
    отправили, нельзя.
    """
    if bot_id in _instances:
        return _instances[bot_id]

    from tg_repost import managed_bots_repo

    view = managed_bots_repo.get(bot_id)
    if view is None or not view.is_active:
        return None
    token = managed_bots_repo.decrypt_token(bot_id)
    if not token:
        managed_bots_repo.record_error(bot_id, "Токен не расшифровывается")
        return None

    from aiogram import Bot

    instance = Bot(token=token)
    _instances[bot_id] = instance
    return instance


def active_bots() -> dict[int, Any]:
    """Все включённые боты — для запуска опроса.

    Возвращается СЛОВАРЬ, а не список: обработчику апдейта нужно от бота
    попасть к строке реестра, а обратный поиск по токену означал бы
    расшифровку на каждое сообщение.
    """
    from tg_repost import managed_bots_repo

    result: dict[int, Any] = {}
    for view in managed_bots_repo.list_all(only_active=True):
        instance = bot_for(view.id)
        if instance is not None:
            result[view.id] = instance
    return result


def bot_id_of(bot: Any) -> int | None:
    """Какой строке реестра принадлежит этот экземпляр.

    Нужно обработчикам: апдейт приносит бот, а сценарий привязан к строке.
    """
    for bot_id, instance in _instances.items():
        if instance is bot:
            return bot_id
    return None


async def forget(bot_id: int) -> None:
    """Выбросить экземпляр — после смены токена или выключения.

    Сессия закрывается явно: брошенный клиент держит открытое соединение, и
    при перенастройке ботов их накопится столько же, сколько было правок.
    """
    instance = _instances.pop(bot_id, None)
    if instance is None:
        return
    try:
        await instance.session.close()
    except Exception as exc:  # noqa: BLE001 — закрытие не должно ломать перенастройку
        logger.warning("F75: сессия бота #%d не закрылась: %s", bot_id, exc)


async def forget_all() -> None:
    for bot_id in list(_instances):
        await forget(bot_id)
