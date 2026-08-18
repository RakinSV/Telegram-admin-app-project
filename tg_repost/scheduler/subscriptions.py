"""Закрытие доступа по окончании подписки (F49).

КИК — ЭТО БАН + СНЯТИЕ БАНА, а не просто бан. `banChatMember` без снятия
оставляет человека в чёрном списке: он оплатит снова и не сможет войти по
новой ссылке. Пара «забанить и тут же разбанить» удаляет из канала, не
закрывая дорогу обратно, — а обратная дорога здесь и есть смысл платной
подписки.

СБОЙ НА ОДНОМ НЕ ОСТАНАВЛИВАЕТ ОСТАЛЬНЫХ. Человек мог сам выйти из канала,
и Telegram ответит ошибкой; считать это поводом не обрабатывать очередь —
значит копить неснятые доступы из-за одной строки.

ЗАПИСЬ О ЗАКРЫТИИ СТАВИТСЯ ТОЛЬКО ПОСЛЕ УСПЕХА. Пометить закрытым, а потом
упасть — значит оставить человека в канале навсегда: следующий проход его
уже не увидит.
"""

from __future__ import annotations

from tg_repost import subscriptions_repo as subs
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)


async def revoke_expired_subscriptions(bot) -> int:  # Bot из aiogram/PTB
    """Закрыть доступ всем, у кого подписка кончилась. Возвращает число."""
    due = subs.due_for_revoke()
    if not due:
        return 0

    logger.info("F49: подписок к закрытию — %d", len(due))
    closed = 0
    for view in due:
        try:
            await bot.ban_chat_member(chat_id=view.chat_id, user_id=view.user_id)
            await bot.unban_chat_member(
                chat_id=view.chat_id, user_id=view.user_id, only_if_banned=True,
            )
        except Exception as exc:  # noqa: BLE001
            # Человек мог выйти сам — это не наша ошибка, но и не повод
            # держать подписку активной вечно.
            message = str(exc).lower()
            if "not found" in message or "not a member" in message:
                subs.mark_revoked(view.chat_id, view.user_id)
                logger.info(
                    "F49: %s уже не в канале %s — подписка закрыта",
                    view.user_id, view.chat_id,
                )
                continue
            logger.warning(
                "F49: не удалось закрыть доступ %s в %s: %s",
                view.user_id, view.chat_id, exc,
            )
            continue

        subs.mark_revoked(view.chat_id, view.user_id)
        closed += 1

    return closed
