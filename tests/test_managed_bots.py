"""Реестр ботов (F75).

Токен бота — полный доступ к чужому боту: кто им владеет, тот пишет от его
имени всем, кто когда-либо его запускал. Поэтому тесты здесь не про «строка
сохранилась», а про то, что токен не утекает и что неверный не принимается
молча.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tg_repost import managed_bots_repo as bots
from tg_repost.db.models import Flow, ManagedBot
from tg_repost.db.session import session_scope

TOKEN = "123456789:AAHrealistic_looking_token_value_x"
OTHER_TOKEN = "987654321:BBHanother_realistic_token_value"


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(Flow).delete()
            session.query(ManagedBot).delete()

    _wipe()
    yield
    _wipe()


def _accepts(username: str = "my_bot"):
    """Telegram признаёт токен своим."""
    return patch.object(
        bots, "verify_token", AsyncMock(return_value=(True, username)),
    )


def _rejects(reason: str = "Unauthorized"):
    return patch.object(
        bots, "verify_token", AsyncMock(return_value=(False, reason)),
    )


# --- токен не утекает ---


async def test_token_is_not_in_the_description():
    """ГЛАВНОЕ СВОЙСТВО.

    В объекте для шаблона поля с токеном нет вовсе — не замаскировано, а
    отсутствует. То, чего нет, невозможно случайно вывести на страницу.
    """
    with _accepts():
        bot_id = await bots.save("Мой бот", TOKEN, is_active=True)

    view = bots.get(bot_id)

    assert view is not None
    assert TOKEN not in repr(view)
    assert not hasattr(view, "token")
    assert not hasattr(view, "token_encrypted")


async def test_token_is_stored_encrypted():
    with _accepts():
        await bots.save("Мой бот", TOKEN)

    with session_scope() as session:
        row = session.query(ManagedBot).one()

        assert TOKEN not in row.token_encrypted
        assert TOKEN not in row.token_hint


async def test_hint_shows_only_the_tail():
    """Отличить два токена в списке иначе нечем, но и показывать больше
    четырёх знаков незачем."""
    with _accepts():
        bot_id = await bots.save("Мой бот", TOKEN)

    view = bots.get(bot_id)

    assert view is not None
    assert view.token_hint.endswith(TOKEN[-4:])
    assert len(view.token_hint) <= 8


async def test_token_comes_back_only_through_the_named_function():
    with _accepts():
        bot_id = await bots.save("Мой бот", TOKEN)

    assert bots.decrypt_token(bot_id) == TOKEN


# --- проверка токена ---


async def test_rejected_token_is_not_saved():
    """Неверный токен, принятый молча, — это бот, который «есть в списке и не
    работает», и разбираться владелец будет по логам."""
    with _rejects("Unauthorized"), pytest.raises(bots.InvalidBot) as exc:
        await bots.save("Мой бот", TOKEN)

    assert "Unauthorized" in str(exc.value)
    assert bots.list_all() == []


@pytest.mark.parametrize("bad", ["мусор", "12345", "", "нет-двоеточия-совсем-длинная"])
async def test_malformed_token_is_refused_without_asking_telegram(bad):
    """Явную ерунду отсекаем до сетевого вызова."""
    asked = AsyncMock()
    with patch.object(bots, "verify_token", asked), pytest.raises(bots.InvalidBot):
        await bots.save("Мой бот", bad)

    assert asked.await_count == 0


async def test_username_is_taken_from_telegram():
    """Помнить, какому боту принадлежит строка токена, человек не обязан."""
    with _accepts("shop_helper_bot"):
        bot_id = await bots.save("Помощник", TOKEN)

    view = bots.get(bot_id)
    assert view is not None and view.username == "shop_helper_bot"


async def test_same_bot_twice_is_refused():
    """Два опроса одного апдейта означают двойные ответы человеку."""
    with _accepts("same_bot"):
        await bots.save("Первый", TOKEN)

        with pytest.raises(bots.InvalidBot) as exc:
            await bots.save("Второй", OTHER_TOKEN)

    assert "уже добавлен" in str(exc.value)


# --- правка ---


async def test_empty_token_on_edit_keeps_the_old_one():
    """Показать сохранённый токен невозможно, поэтому пустое поле означает
    «не меняли»: иначе бот ломался бы при каждом переименовании."""
    with _accepts():
        bot_id = await bots.save("Мой бот", TOKEN)

    await bots.save("Переименованный", "", bot_id=bot_id)

    assert bots.decrypt_token(bot_id) == TOKEN
    view = bots.get(bot_id)
    assert view is not None and view.name == "Переименованный"


async def test_new_bot_without_token_is_refused():
    with pytest.raises(bots.InvalidBot):
        await bots.save("Без токена", "")


async def test_new_token_clears_the_old_error():
    """Прежняя ошибка была про прежний токен."""
    with _accepts():
        bot_id = await bots.save("Мой бот", TOKEN)
    bots.record_error(bot_id, "Unauthorized")

    with _accepts():
        await bots.save("Мой бот", OTHER_TOKEN, bot_id=bot_id)

    view = bots.get(bot_id)
    assert view is not None and view.last_error is None


async def test_error_is_remembered_for_the_owner():
    """Владелец видит «включён» и тишину; без причины на странице он полезет
    в логи контейнера."""
    with _accepts():
        bot_id = await bots.save("Мой бот", TOKEN, is_active=True)

    bots.record_error(bot_id, "Unauthorized: bot token is invalid")

    view = bots.get(bot_id)
    assert view is not None and "Unauthorized" in (view.last_error or "")


# --- удаление ---


async def test_bot_with_flows_is_switched_off_not_deleted():
    """Сценарий без бота запускать нечем, а люди внутри него ссылаются на
    узлы: удаление оставило бы их в пустоте."""
    with _accepts():
        bot_id = await bots.save("Мой бот", TOKEN, is_active=True)
    with session_scope() as session:
        session.add(Flow(bot_id=bot_id, name="Сценарий"))

    assert await _delete(bot_id) is False
    view = bots.get(bot_id)
    assert view is not None and view.is_active is False


async def test_bot_without_flows_is_deleted():
    with _accepts():
        bot_id = await bots.save("Мой бот", TOKEN)

    assert await _delete(bot_id) is True
    assert bots.list_all() == []


async def _delete(bot_id: int) -> bool:
    return bots.delete(bot_id)


# --- список ---


async def test_only_active_bots_are_offered_for_polling():
    """Опрос поднимает только включённые: выключенный бот не должен
    отвечать людям."""
    with _accepts("first_bot"):
        await bots.save("Первый", TOKEN, is_active=True)
    with _accepts("second_bot"):
        await bots.save("Второй", OTHER_TOKEN, is_active=False)

    names = [b.name for b in bots.list_all(only_active=True)]

    assert names == ["Первый"]


async def test_listing_counts_flows():
    """Сколько сценариев на боте — то, что владелец спрашивает первым."""
    with _accepts():
        bot_id = await bots.save("Мой бот", TOKEN)
    with session_scope() as session:
        session.add(Flow(bot_id=bot_id, name="Первый"))
        session.add(Flow(bot_id=bot_id, name="Второй"))

    assert bots.list_all()[0].flows_count == 2

async def test_token_of_another_process_is_refused(monkeypatch):
    """ДВА ОПРОСА ОДНОГО БОТА — ЭТО ПОТЕРЯННЫЕ СООБЩЕНИЯ ЛЮДЕЙ.

    Telegram отдаёт `getUpdates` ровно одному слушателю: второй получает 409,
    и апдейты начинают доставаться то одному процессу, то другому. Владелец
    при этом видит рабочего бота, который «иногда не отвечает». Соблазн
    вставить сюда токен бота модерации большой — раз «всё в конструкторе».
    """
    monkeypatch.setattr(
        bots, "_belongs_to_another_process",
        lambda _token: "бот модерации",
    )

    with pytest.raises(bots.InvalidBot) as exc:
        await bots.save("Свой", TOKEN, is_active=True)

    assert "уже занят" in str(exc.value)


async def test_free_token_passes_the_occupancy_check(monkeypatch):
    """Обратная проверка: чужих токенов нет — сохранение идёт своим чередом."""
    monkeypatch.setattr(
        bots, "_belongs_to_another_process", lambda _token: None,
    )
    with patch(
        "tg_repost.managed_bots_repo.verify_token",
        new=AsyncMock(return_value=(True, "free_bot")),
    ):
        bot_id = await bots.save("Свободный", TOKEN)

    assert bots.get(bot_id) is not None
