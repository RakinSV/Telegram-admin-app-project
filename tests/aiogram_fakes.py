"""Поддельные объекты aiogram для тестов бота модерации.

ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ. После перевода бота с python-telegram-bot на aiogram
обработчики принимают НАСТОЯЩИЕ типы: `CallbackQuery`, `Message`,
`ChatMemberUpdated`. Подделка через `SimpleNamespace` больше не проходит — и
это хорошо: код различает `Message` и `InaccessibleMessage` (заглушку, которую
Telegram отдаёт вместо сообщений старше 48 часов), а самодельный объект прошёл
бы обе ветки одинаково и скрыл бы разницу.

Собирать эти объекты в каждом тесте — двадцать строк на вызов, поэтому они
собираются здесь. Бот всегда подделан `AsyncMock`: сеть в тестах не нужна, а
проверять удобно по вызовам самого бота.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

from aiogram.types import (
    CallbackQuery,
    Chat,
    ChatJoinRequest,
    ChatMemberAdministrator,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberOwner,
    ChatMemberUpdated,
    Message,
    PhotoSize,
    User,
)

OWNER_ID = 1  # совпадает с TG_OWNER_USER_ID из conftest


def fake_bot() -> AsyncMock:
    """Бот, у которого можно спросить, что он отправил."""
    return AsyncMock()


def fake_user(user_id: int = OWNER_ID, username: str | None = None) -> User:
    return User(
        id=user_id, is_bot=False, first_name="Test User", username=username,
    )


def fake_message(
    bot: AsyncMock, *, with_photo: bool = False, chat_id: int = OWNER_ID,
    text: str | None = "текст",
) -> Message:
    """Сообщение, привязанное к поддельному боту.

    Привязка (`as_`) обязательна: без неё `message.edit_text()` не знает, кому
    отправлять правку, и падает на «bot is not set».
    """
    photo = (
        [PhotoSize(file_id="cover", file_unique_id="uniq", width=100, height=100)]
        if with_photo else None
    )
    return Message(
        message_id=100,
        date=datetime.now(timezone.utc),
        chat=Chat(id=chat_id, type="private"),
        from_user=fake_user(),
        text=None if with_photo else text,
        caption="подпись" if with_photo else None,
        photo=photo,
    ).as_(bot)


def fake_callback(
    bot: AsyncMock, data: str, *, with_photo: bool = False,
    user_id: int = OWNER_ID,
) -> CallbackQuery:
    """Нажатие кнопки от имени владельца."""
    return CallbackQuery(
        id="cb-1",
        from_user=fake_user(user_id),
        chat_instance="chat-instance",
        data=data,
        message=fake_message(bot, with_photo=with_photo),
    ).as_(bot)


def fake_join_request(
    bot: AsyncMock, chat_id: int, user_id: int, username: str | None = None,
    bio: str | None = None, invite_link: str | None = None,
) -> ChatJoinRequest:
    from aiogram.types import ChatInviteLink

    link = (
        ChatInviteLink(
            invite_link=invite_link, creator=fake_user(), creates_join_request=True,
            is_primary=False, is_revoked=False,
        )
        if invite_link else None
    )
    return ChatJoinRequest(
        chat=Chat(id=chat_id, type="supergroup", title="Test Group"),
        from_user=fake_user(user_id, username),
        user_chat_id=user_id,
        date=datetime.now(timezone.utc),
        bio=bio,
        invite_link=link,
    ).as_(bot)


def _member(status: str, user: User, *, can_post: bool | None = None):
    """Участник нужного статуса. Тип у aiogram свой на каждый статус."""
    if status == "creator":
        return ChatMemberOwner(user=user, is_anonymous=False)
    if status == "administrator":
        return ChatMemberAdministrator(
            user=user, can_be_edited=False, is_anonymous=False,
            can_manage_chat=True, can_delete_messages=True,
            can_manage_video_chats=True, can_restrict_members=True,
            can_promote_members=False, can_change_info=True,
            can_invite_users=True,
            # Права на истории обязательны в схеме Bot API 7.x — заполняем,
            # чтобы подделка была валидной, а не «почти как настоящая».
            can_post_stories=False, can_edit_stories=False,
            can_delete_stories=False,
            can_post_messages=can_post,
        )
    if status == "member":
        return ChatMemberMember(user=user)
    return ChatMemberLeft(user=user)


def fake_membership(
    *, chat_id: int, chat_type: str = "channel", title: str = "Канал",
    old_status: str = "left", new_status: str = "administrator",
    can_post: bool | None = None, user_id: int = 777,
    invite_link: str | None = None,
) -> ChatMemberUpdated:
    """Смена статуса участника (или самого бота) в чате."""
    from aiogram.types import ChatInviteLink

    user = fake_user(user_id)
    link = (
        ChatInviteLink(
            invite_link=invite_link, creator=fake_user(), creates_join_request=False,
            is_primary=False, is_revoked=False, name="кампания",
        )
        if invite_link else None
    )
    return ChatMemberUpdated(
        chat=Chat(id=chat_id, type=chat_type, title=title),
        from_user=fake_user(),
        date=datetime.now(timezone.utc),
        old_chat_member=_member(old_status, user),
        new_chat_member=_member(new_status, user, can_post=can_post),
        invite_link=link,
    )


def sent_methods(bot: AsyncMock) -> list:
    """Что бот отправил: список объектов-методов aiogram.

    Правка сообщения у aiogram — это вызов бота с объектом метода
    (`EditMessageText`, `EditMessageCaption`), а не именованный метод, поэтому
    проверять удобнее так.
    """
    return [call.args[0] for call in bot.call_args_list if call.args]
