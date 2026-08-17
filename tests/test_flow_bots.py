"""Живые экземпляры ботов реестра (F75).

Здесь проверяется то, что владелец делает руками в админке: добавил бота,
выключил, сменил токен. Каждое из этих действий должно немедленно отражаться
на том, кто именно опрашивает Telegram, — иначе выключенный бот продолжает
отвечать людям, а бот с новым токеном стучится старым.
"""

from __future__ import annotations

import pytest

from tg_repost import flow_bots, managed_bots_repo
from tg_repost.db.models import Flow, ManagedBot
from tg_repost.db.session import session_scope

# Формат Telegram: «цифры:буквы». Сетевых вызовов здесь нет — `Bot(token=...)`
# только запоминает строку, но формат он проверяет.
TOKEN = "111111111:AAHkQeExampleTokenValueForTestsOnly1"
OTHER_TOKEN = "222222222:BBLmWrAnotherTokenValueForTestsOnly2"


@pytest.fixture(autouse=True)
async def _clean():
    await flow_bots.forget_all()
    with session_scope() as session:
        session.query(Flow).delete()
        session.query(ManagedBot).delete()
    yield
    await flow_bots.forget_all()
    with session_scope() as session:
        session.query(Flow).delete()
        session.query(ManagedBot).delete()


def _add(name: str, token: str = TOKEN, *, active: bool = True,
         encrypted: str | None = None) -> int:
    """Строка реестра без обращения к Telegram.

    `managed_bots_repo.save` намеренно ходит в `getMe`; здесь проверяется не
    он, а подъём экземпляров, поэтому строка пишется напрямую.
    """
    if encrypted is None:
        encrypted, hint = managed_bots_repo._encrypt(token)
    else:
        hint = "••••"
    with session_scope() as session:
        row = ManagedBot(
            name=name, token_encrypted=encrypted, token_hint=hint,
            username=name.lower(), is_active=active,
        )
        session.add(row)
        session.flush()
        return row.id


async def test_unknown_bot_has_no_instance():
    assert flow_bots.bot_for(999) is None


async def test_switched_off_bot_does_not_get_raised():
    """Выключатель в админке обязан действительно останавливать бота.

    Иначе владелец «выключил» бота, а тот продолжает отвечать людям.
    """
    bot_id = _add("Выключенный", active=False)

    assert flow_bots.bot_for(bot_id) is None


async def test_instance_is_reused():
    """Второй вызов не должен создавать второй клиент: на каждом висит
    открытое соединение, и за день работы их накопилось бы по числу сообщений.
    """
    bot_id = _add("Рабочий")

    first = flow_bots.bot_for(bot_id)
    second = flow_bots.bot_for(bot_id)

    assert first is not None
    assert first is second


async def test_unreadable_token_is_reported_to_the_owner():
    """Мастер-ключ сменили — токен больше не расшифровать.

    Владелец увидит «включён» и тишину; без записанной причины он полезет в
    логи контейнера, а это ровно то, от чего админка избавляет.
    """
    bot_id = _add("Испорченный", encrypted="это-не-шифротекст")

    assert flow_bots.bot_for(bot_id) is None
    view = managed_bots_repo.get(bot_id)
    assert view is not None and view.last_error is not None


async def test_active_bots_are_keyed_by_registry_row():
    """Обработчику апдейта нужно от бота попасть к строке реестра: обратный
    поиск по токену означал бы расшифровку на каждое сообщение."""
    first = _add("Первый")
    second = _add("Второй", OTHER_TOKEN)
    _add("Третий", active=False)

    raised = flow_bots.active_bots()

    assert set(raised) == {first, second}
    assert flow_bots.bot_id_of(raised[first]) == first
    assert flow_bots.bot_id_of(raised[second]) == second


async def test_foreign_instance_belongs_to_nobody():
    from aiogram import Bot

    stranger = Bot(token=TOKEN)
    try:
        assert flow_bots.bot_id_of(stranger) is None
    finally:
        await stranger.session.close()


async def test_new_token_replaces_the_instance():
    """ГЛАВНОЕ ЗДЕСЬ. Сменив токен, владелец ждёт, что бот заработает по
    новому. Кэш по идентификатору строки без сброса стучался бы старым до
    перезапуска процесса."""
    bot_id = _add("Переназначенный")
    before = flow_bots.bot_for(bot_id)
    assert before is not None and before.token == TOKEN

    with session_scope() as session:
        row = session.get(ManagedBot, bot_id)
        row.token_encrypted, row.token_hint = managed_bots_repo._encrypt(OTHER_TOKEN)
    await flow_bots.forget(bot_id)

    after = flow_bots.bot_for(bot_id)

    assert after is not None
    assert after.token == OTHER_TOKEN
    assert after is not before


async def test_forgetting_closes_the_connection():
    """Брошенный клиент держит открытое соединение: при перенастройке ботов их
    накопится столько же, сколько было правок."""
    bot_id = _add("Закрываемый")
    instance = flow_bots.bot_for(bot_id)
    assert instance is not None
    # Соединение создаётся лениво — поднимаем его, чтобы было что закрывать.
    connection = await instance.session.create_session()
    assert connection.closed is False

    await flow_bots.forget(bot_id)

    assert connection.closed is True
    assert flow_bots.bot_id_of(instance) is None


async def test_forgetting_an_absent_bot_is_harmless():
    await flow_bots.forget(12345)


async def test_forget_all_clears_everything():
    _add("Один")
    _add("Два", OTHER_TOKEN)
    flow_bots.active_bots()

    await flow_bots.forget_all()

    assert flow_bots._instances == {}
