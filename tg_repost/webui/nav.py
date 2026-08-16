"""Состав бокового меню (аудит юзабилити 2026-08-16).

ПОЧЕМУ ЭТО ОТДЕЛЬНЫЙ МОДУЛЬ, А НЕ РАЗМЕТКА. За четыре сессии меню выросло до
34 пунктов, добавляемых по одному вместе с фичами, — плоским списком примерно
на 1200 пикселей высоты. На ноутбуке он не помещается целиком, и найти в нём
нужное можно только перечитав всё подряд. Владелец так и сказал: «зашёл в
админку, ничего не понятно».

ГРУППЫ СОБРАНЫ ПО ЗАДАЧЕ ВЛАДЕЛЬЦА, А НЕ ПО УСТРОЙСТВУ КОДА. «Магазин» лежит
рядом с «Подписками» и «Криптой», потому что это всё про деньги, а не потому,
что у них соседние номера фич. Человек ищет «где посмотреть выручку», а не
«где F69».

ПОРЯДОК ГРУПП — ПО ЧАСТОТЕ, А НЕ ПО ВАЖНОСТИ. Контент открывают каждый день,
систему — раз в месяц. Редкое внизу, частое вверху.

Пункт, недоступный роли, скрывается вместе с проверкой `can_open`, а группа,
из которой скрылось всё, не рисует и заголовок: пустая рубрика хуже, чем её
отсутствие, — она заставляет искать то, чего нет.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NavItem:
    href: str
    label_key: str
    # Подсвечивать пункт и на вложенных путях (`/sources/42`).
    prefix: bool = False


@dataclass(frozen=True)
class NavGroup:
    title_key: str | None
    items: tuple[NavItem, ...]


NAV: tuple[NavGroup, ...] = (
    # Без заголовка: две точки входа, с которых начинается любой день.
    NavGroup(None, (
        NavItem("/", "nav.dashboard"),
        NavItem("/stats", "nav.stats", prefix=True),
    )),
    NavGroup("nav.group.content", (
        NavItem("/sources", "nav.sources", prefix=True),
        NavItem("/targets", "nav.targets"),
        NavItem("/moderation", "nav.moderation", prefix=True),
        NavItem("/calendar", "nav.calendar", prefix=True),
        NavItem("/polls", "nav.polls"),
        NavItem("/ads", "nav.ads"),
    )),
    NavGroup("nav.group.audience", (
        NavItem("/contacts", "nav.contacts", prefix=True),
        NavItem("/segments", "nav.segments"),
        NavItem("/broadcasts", "nav.broadcasts", prefix=True),
        NavItem("/funnels", "nav.funnels", prefix=True),
        NavItem("/invites", "nav.invites"),
        NavItem("/contests", "nav.contests"),
        NavItem("/support", "nav.support", prefix=True),
    )),
    NavGroup("nav.group.money", (
        NavItem("/subscriptions", "nav.subscriptions"),
        NavItem("/shop", "nav.shop", prefix=True),
        NavItem("/crypto", "nav.crypto"),
        NavItem("/affiliate", "nav.affiliate", prefix=True),
        NavItem("/ad-requests", "nav.ad_requests"),
        NavItem("/mediakit", "nav.mediakit"),
    )),
    NavGroup("nav.group.guardian", (
        NavItem("/guardian", "nav.guardian_dashboard"),
        NavItem("/guardian/settings", "nav.guardian_settings"),
        NavItem("/guardian/stopwords", "nav.guardian_stopwords"),
        NavItem("/guardian/domains", "nav.guardian_domains"),
        NavItem("/guardian/trusted", "nav.guardian_trusted"),
    )),
    NavGroup("nav.group.system", (
        NavItem("/settings", "nav.settings"),
        NavItem("/users", "nav.users"),
        NavItem("/integrations", "nav.integrations"),
        NavItem("/components", "nav.components"),
        NavItem("/telethon-sessions", "nav.telethon_sessions"),
        NavItem("/audit", "nav.audit"),
        NavItem("/logs", "nav.logs"),
        NavItem("/export", "nav.export"),
    )),
)


def all_hrefs() -> list[str]:
    """Все адреса меню — для проверок полноты."""
    return [item.href for group in NAV for item in group.items]
