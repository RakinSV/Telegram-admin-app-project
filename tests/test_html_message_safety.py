"""Подстановка текста в сообщения с parse_mode=HTML (найдено 2026-08-19).

Guardian и Engage шлют ВСЕ сообщения с `parse_mode=ParseMode.HTML` — это
дефолт бота (`guardian/bot.py`, `engage/bot.py`). Значит, любой текст,
подставленный в сообщение без экранирования, Telegram пытается разобрать как
разметку.

ЧЕМ ЭТО ГРОЗИТ НА САМОМ ДЕЛЕ. Владелец заводит в магазине товар «Курс C++
<с нуля>» — название проходит без единой проверки, в базе оно есть, в админке
видно. А покупатель нажимает кнопку и не получает НИЧЕГО: Telegram отвечает
«can't parse entities: Unsupported start tag», сообщение не уходит вовсе.
Снаружи это выглядит как «магазин сломался», и по логам админки не видно
ничего — товар-то на месте.

Отдельно про имя участника: оно приходит от постороннего, и там подстановка
опаснее — `<b>Администратор</b>` подделал бы вид сообщения. Этот путь уже
закрыт (`guardian/handlers/join.py::_display_name` экранирует внутри), и
здесь стоит проверка, чтобы закрытым и остался.
"""

from __future__ import annotations

import pytest

from tests.aiogram_fakes import fake_bot, fake_callback, fake_user, sent_methods

# Название, на котором Telegram спотыкается: «<с» — не тег из белого списка.
NASTY = 'Курс C++ <с нуля> & "практика"'


def _texts(bot) -> list[str]:
    """Весь текст, который бот попытался отправить."""
    out = []
    for method in sent_methods(bot):
        for attr in ("text", "caption", "message"):
            value = getattr(method, attr, None)
            if isinstance(value, str):
                out.append(value)
    for call in bot.method_calls:
        for value in list(call.args) + list(call.kwargs.values()):
            if isinstance(value, str):
                out.append(value)
    return out


def _assert_escaped(texts: list[str], raw_fragment: str, where: str) -> None:
    """Сырой фрагмент не должен уйти в Telegram как есть."""
    joined = "\n".join(texts)
    assert joined, f"{where}: бот вообще ничего не отправил — проверять нечего"
    assert raw_fragment not in joined, (
        f"{where}: «{raw_fragment}» ушёл в сообщение неэкранированным — "
        f"Telegram ответит «can't parse entities», и сообщение не дойдёт вовсе.\n"
        f"Отправлено: {joined[:300]}"
    )
    assert "&lt;" in joined or "&amp;" in joined, (
        f"{where}: экранирования не видно вообще"
    )


@pytest.fixture
def product_with_nasty_name():
    from tg_repost.db.models import Product
    from tg_repost.db.session import session_scope

    with session_scope() as session:
        product = Product(name=NASTY, price=100.0, currency="RUB",
                          is_active=True, description="описание")
        session.add(product)
        session.flush()
        product_id = product.id
    yield product_id
    with session_scope() as session:
        session.query(Product).filter(Product.id == product_id).delete()


# --- магазин ---


@pytest.mark.asyncio
async def test_product_card_escapes_the_name(product_with_nasty_name, monkeypatch):
    """Карточка товара — первое, что видит покупатель."""
    from engage.handlers import shop as handlers

    from tg_repost import crypto_rails_repo

    # Ветка «есть и карта, и крипта» — та, где название подставляется в текст.
    # Без этого обработчик уходит в «оплата не настроена» и название не
    # печатает вовсе, а тест проверял бы пустоту.
    monkeypatch.setattr(handlers, "_enabled", lambda: True)
    monkeypatch.setattr(handlers, "_provider_token", lambda: "111:PROVIDER")
    monkeypatch.setattr(crypto_rails_repo, "rail_for_product",
                        lambda _pid: object())
    bot = fake_bot()
    callback = fake_callback(bot, f"buy:{product_with_nasty_name}")

    await handlers.on_buy(callback, bot)

    _assert_escaped(_texts(bot), "<с нуля>", "карточка товара")


# --- конкурсы ---


@pytest.mark.asyncio
async def test_contest_join_escapes_the_title(monkeypatch):
    """Название конкурса владелец пишет в админке — тем же способом, что и
    название товара, и с тем же результатом."""
    from datetime import datetime, timedelta, timezone

    from engage.handlers import contest as handlers
    from tests.aiogram_fakes import fake_message
    from tg_repost.db.models import Contest
    from tg_repost.db.session import session_scope

    with session_scope() as session:
        entry = Contest(
            title=NASTY, prize="Приз <главный>", winners_count=1, chat_id=-1001,
            starts_at=datetime.now(timezone.utc) - timedelta(days=1),
            ends_at=datetime.now(timezone.utc) + timedelta(days=1),
            draw_seed="seed-1",
        )
        session.add(entry)
        session.flush()
        contest_id = entry.id

    bot = fake_bot()
    message = fake_message(bot)

    try:
        await handlers.handle_contest_start(
            bot, str(contest_id), fake_user(user_id=555), message,
        )
        _assert_escaped(_texts(bot), "<с нуля>", "запись на конкурс")
    finally:
        with session_scope() as session:
            session.query(Contest).filter(Contest.id == contest_id).delete()


# --- имя участника (обратная проверка, путь уже закрыт) ---


def test_member_display_name_stays_escaped():
    """Имя приходит от постороннего: `<b>Администратор</b>` подделал бы вид
    сообщения. Проверка стоит на том, чтобы закрытый путь не открыли обратно."""
    from guardian.handlers.join import _display_name

    user = fake_user(user_id=777, username=None)
    object.__setattr__(user, "first_name", "<b>Администратор</b>")

    rendered = _display_name(user)

    assert "<b>" not in rendered, "имя участника снова уходит как разметка"
    assert "&lt;b&gt;" in rendered
