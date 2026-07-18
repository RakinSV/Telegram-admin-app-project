"""Регрессионные тесты верификации новых участников (G01) — конкретно
сценарий, найденный на security-аудите: `chat_member`-апдейт в aiogram
резолвит `EventContext.user` как `from_user` (совершившего действие), а НЕ
`new_chat_member.user` (реального нового участника) — если бы капча
опиралась на это (как в первой версии, через FSM), добавивший участника мог
бы пройти капчу ВМЕСТО него. Текущая реализация не использует FSM вообще и
явно сверяет `callback.from_user.id` с `target_user_id`, закодированным в
`callback_data` — тесты ниже проверяют именно это."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from guardian import settings_store
from guardian.config import invalidate_settings_cache
from guardian.handlers import join
from guardian.db.models import BotConfig, Member
from guardian.db.session import session_scope

_CHAT_ID = -100123  # GUARDIAN_GROUP_ID из tests/conftest.py


def _clear_members() -> None:
    with session_scope() as session:
        session.query(Member).delete()
        session.query(BotConfig).delete()


@pytest.fixture(autouse=True)
def _isolated_pending():
    join._pending.clear()
    _clear_members()
    invalidate_settings_cache()
    settings_store.sync_protected_chat_ids([_CHAT_ID])  # F28: список, не одна группа
    yield
    join._pending.clear()
    _clear_members()
    invalidate_settings_cache()


def _fake_user(
    user_id: int, username: str | None = "newuser", is_bot: bool = False
) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        username=username,
        first_name="New",
        full_name="New User",
        is_bot=is_bot,
    )


def _fake_event(chat_id: int, joiner_id: int, username: str | None = "newuser") -> SimpleNamespace:
    """`new_chat_member.user` — реальный новый участник. Умышленно НЕ
    выставляем отдельный `from_user` на событии — `on_new_member` его не
    читает вообще (это и есть суть фикса: `from_user` больше нигде не
    участвует в определении, для кого капча)."""
    return SimpleNamespace(
        chat=SimpleNamespace(id=chat_id),
        new_chat_member=SimpleNamespace(user=_fake_user(joiner_id, username=username)),
    )


async def test_on_new_member_pending_keyed_by_joining_user_not_actor():
    # chat_id совпадает с GUARDIAN_GROUP_ID из tests/conftest.py по умолчанию.
    bot = AsyncMock()
    bot.restrict_chat_member = AsyncMock()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=555))
    # G15 (анализ профиля) вызывает эти два метода при каждом вступлении —
    # без явных конкретных return_value голый AsyncMock() каскадно
    # авто-мокает даже `.bio.lower()` в коротину, которую никто не await'ит
    # (найдено эмпирически при добавлении G15).
    bot.get_user_profile_photos = AsyncMock(return_value=SimpleNamespace(total_count=1))
    bot.get_chat = AsyncMock(return_value=SimpleNamespace(bio=""))
    scheduler = MagicMock()

    chat_id, joiner_id = -100123, 2002
    event = _fake_event(chat_id, joiner_id)
    await join.on_new_member(event, bot, scheduler)

    assert (chat_id, joiner_id) in join._pending
    bot.restrict_chat_member.assert_awaited_once_with(
        chat_id, joiner_id, permissions=join._MUTED_PERMISSIONS
    )
    scheduler.add_job.assert_called_once()
    _, kwargs = scheduler.add_job.call_args
    assert kwargs["args"] == [bot, chat_id, joiner_id]


async def test_suspicious_profile_forces_math_captcha():
    """G15: подозрительный профиль (нет username, нет фото, "плохая" био) —
    капча принудительно `math`, даже если сконфигурирован `button` (тот
    решается одним кликом без чтения текста)."""
    from guardian import settings_store

    settings_store.save_setting("captcha_type", "button", "str")
    settings_store.save_setting("profile_suspicion_threshold", 2, "int")

    bot = AsyncMock()
    bot.restrict_chat_member = AsyncMock()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=555))
    bot.get_user_profile_photos = AsyncMock(return_value=SimpleNamespace(total_count=0))
    bot.get_chat = AsyncMock(return_value=SimpleNamespace(bio="crypto заработок"))
    scheduler = MagicMock()

    chat_id, joiner_id = -100123, 3003
    event = _fake_event(chat_id, joiner_id, username=None)
    await join.on_new_member(event, bot, scheduler)

    pending = join._pending[(chat_id, joiner_id)]
    assert len(pending.options) == 4  # math-капча даёт 4 варианта, button — 1


async def test_captcha_answer_rejected_when_clicker_is_not_the_target():
    """Ядро фикса: у капчи, выданной участнику 2002, кнопки кодируют
    target_user_id=2002 в callback_data — клик от ЛЮБОГО другого id (в т.ч.
    от добавившего участника) должен быть отклонён ДО обращения к `_pending`,
    и запись в `_pending` должна остаться нетронутой (второй попытки для
    настоящего участника это не портит)."""
    chat_id, joiner_id, attacker_id = -100123, 2002, 1001
    join._pending[(chat_id, joiner_id)] = join._PendingCaptcha(
        correct_answer="7", options=["7", "3", "9", "1"], captcha_message_id=555
    )

    bot = AsyncMock()
    scheduler = MagicMock()
    callback = AsyncMock()
    callback.data = (
        f"captcha:{joiner_id}:0"  # правильный индекс, но кликает НЕ joiner_id
    )
    callback.from_user = SimpleNamespace(
        id=attacker_id, username="attacker", full_name="Attacker"
    )
    callback.message = SimpleNamespace(chat=SimpleNamespace(id=chat_id))

    await join.on_captcha_answer(callback, bot, scheduler)

    callback.answer.assert_awaited_once()
    assert "не для тебя" in callback.answer.call_args.args[0]
    bot.restrict_chat_member.assert_not_awaited()
    assert (
        chat_id,
        joiner_id,
    ) in join._pending  # запись не тронута — реальный участник ещё может ответить


async def test_captcha_answer_accepted_for_correct_target_and_answer():
    chat_id, joiner_id = -100123, 2002
    join._pending[(chat_id, joiner_id)] = join._PendingCaptcha(
        correct_answer="7", options=["7", "3", "9", "1"], captcha_message_id=555
    )
    with session_scope() as session:
        session.add(Member(user_id=joiner_id, chat_id=chat_id, is_verified=False))

    bot = AsyncMock()
    bot.get_chat = AsyncMock(return_value=SimpleNamespace(permissions=None))
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=777))
    scheduler = MagicMock()
    callback = AsyncMock()
    callback.data = f"captcha:{joiner_id}:0"  # индекс 0 -> "7", правильный ответ
    callback.from_user = SimpleNamespace(
        id=joiner_id, username="newuser", full_name="New User"
    )
    callback.message = SimpleNamespace(chat=SimpleNamespace(id=chat_id))

    await join.on_captcha_answer(callback, bot, scheduler)

    bot.restrict_chat_member.assert_awaited_once()
    assert (chat_id, joiner_id) not in join._pending
    with session_scope() as session:
        member = (
            session.query(Member)
            .filter(Member.user_id == joiner_id, Member.chat_id == chat_id)
            .one()
        )
        assert member.is_verified is True


async def test_captcha_wrong_answer_does_not_remove_pending():
    chat_id, joiner_id = -100123, 2002
    join._pending[(chat_id, joiner_id)] = join._PendingCaptcha(
        correct_answer="7", options=["7", "3", "9", "1"], captcha_message_id=555
    )
    bot = AsyncMock()
    scheduler = MagicMock()
    callback = AsyncMock()
    callback.data = f"captcha:{joiner_id}:1"  # индекс 1 -> "3", неверно
    callback.from_user = SimpleNamespace(
        id=joiner_id, username="newuser", full_name="New User"
    )
    callback.message = SimpleNamespace(chat=SimpleNamespace(id=chat_id))

    await join.on_captcha_answer(callback, bot, scheduler)

    bot.restrict_chat_member.assert_not_awaited()
    assert (chat_id, joiner_id) in join._pending  # можно пробовать снова


async def test_kick_unverified_noop_if_already_verified():
    """Атомарность через pop: если запись уже забрана (успешная верификация),
    сработавшая следом джоба тайм-аута не должна ничего банить."""
    chat_id, joiner_id = -100123, 2002
    # Симулируем, что on_captcha_answer уже забрал запись (её больше нет).
    assert (chat_id, joiner_id) not in join._pending

    bot = AsyncMock()
    await join._kick_unverified(bot, chat_id, joiner_id)

    bot.ban_chat_member.assert_not_awaited()


async def test_kick_unverified_bans_when_still_pending():
    chat_id, joiner_id = -100123, 2002
    join._pending[(chat_id, joiner_id)] = join._PendingCaptcha(
        correct_answer="7", options=["7"], captcha_message_id=555
    )
    bot = AsyncMock()

    await join._kick_unverified(bot, chat_id, joiner_id)

    bot.ban_chat_member.assert_awaited_once_with(chat_id, joiner_id)
    bot.unban_chat_member.assert_awaited_once()
    assert (chat_id, joiner_id) not in join._pending
