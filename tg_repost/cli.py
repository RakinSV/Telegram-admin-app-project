"""CLI управления источниками и целевыми группами (F01).

Тонкие обёртки над repo-модулями (`sources_repo.py`, `targets_repo.py`,
`ads/repo.py`) — те же функции переиспользует веб-админка (Фаза 5.3), здесь
только парсинг аргументов и текстовый вывод.

Примеры:
    python -m tg_repost.cli add-source @durov
    python -m tg_repost.cli list-sources
    python -m tg_repost.cli remove-source @durov
    python -m tg_repost.cli add-target -1001234567890 --title "Мой канал"
    python -m tg_repost.cli list-targets
    python -m tg_repost.cli init-db        # создать таблицы без alembic (dev)
"""

from __future__ import annotations

import argparse
import getpass
import sys

from tg_repost import sources_repo, targets_repo, telethon_sessions_repo
from tg_repost.ads import repo as ads_repo
from tg_repost.db.models import Base
from tg_repost.db.session import engine
from tg_repost.logging_conf import setup_logging


def cmd_add_source(args: argparse.Namespace) -> int:
    source, created = sources_repo.add_source(args.channel)
    if created:
        print(f"✅ Источник @{source.channel_username} добавлен.")
    else:
        print(f"Источник @{source.channel_username} уже есть — активирован.")
    return 0


def cmd_remove_source(args: argparse.Namespace) -> int:
    source = sources_repo.find_source_by_username(args.channel)
    if source is None:
        print(f"Источник @{sources_repo.normalize_username(args.channel)} не найден.")
        return 1
    sources_repo.deactivate_source(source.id)
    print(f"✅ Источник @{source.channel_username} деактивирован.")
    return 0


def cmd_list_sources(_: argparse.Namespace) -> int:
    sources = sources_repo.list_sources()
    if not sources:
        print("Источников нет.")
        return 0
    print(f"{'ID':<4} {'Акт':<4} {'Username':<22} {'Стиль':<12} "
          f"{'Добор':<8} {'Цели':<18} {'Title'}")
    for s in sources:
        targets = s.target_chat_ids or "все"
        style = s.style_profile or "default"
        enrich = {True: "on", False: "off", None: "глоб."}[s.enrich_sources]
        print(f"{s.id:<4} {'да' if s.is_active else 'нет':<4} "
              f"@{s.channel_username:<21} {style:<12} {enrich:<8} "
              f"{targets:<18} {s.channel_title or ''}")
    return 0


def cmd_set_source_style(args: argparse.Namespace) -> int:
    """F15 — задать стиль-профиль рерайта для источника."""
    from tg_repost.rewriter.client import KNOWN_STYLES, prompt_exists

    style = args.style.strip().lower()
    if not prompt_exists(style):
        print(f"Неизвестный стиль '{style}'. Доступны: {', '.join(KNOWN_STYLES)}")
        return 1
    source = sources_repo.find_source_by_username(args.channel)
    if source is None:
        print(f"Источник @{sources_repo.normalize_username(args.channel)} не найден.")
        return 1
    sources_repo.set_source_style(source.id, style)
    print(f"✅ Источник @{source.channel_username} → стиль '{style}'")
    return 0


def cmd_set_source_enrich(args: argparse.Namespace) -> int:
    """F16 — включить/выключить добор источников для канала."""
    source = sources_repo.find_source_by_username(args.channel)
    if source is None:
        print(f"Источник @{sources_repo.normalize_username(args.channel)} не найден.")
        return 1
    sources_repo.set_source_enrich(source.id, args.mode)
    human = {"on": "включён", "off": "выключен", "default": "по глобальной настройке"}
    print(f"✅ Добор источников для @{source.channel_username}: {human[args.mode]}")
    return 0


def cmd_set_source_targets(args: argparse.Namespace) -> int:
    """F12 — задать/очистить переопределение целей для источника."""
    source = sources_repo.find_source_by_username(args.channel)
    if source is None:
        print(f"Источник @{sources_repo.normalize_username(args.channel)} не найден.")
        return 1
    if args.clear:
        sources_repo.set_source_targets(source.id, None)
        print(f"✅ Переопределение целей для @{source.channel_username} очищено (идёт во все).")
        return 0
    try:
        sources_repo.set_source_targets(source.id, args.chat_ids)
    except ValueError:
        print("Ошибка: chat_ids должны быть числами через запятую.")
        return 1
    print(f"✅ Источник @{source.channel_username} → цели {args.chat_ids}")
    return 0


def cmd_add_target(args: argparse.Namespace) -> int:
    target, created = targets_repo.add_target(args.chat_id, args.title)
    if created:
        print(f"✅ Целевая группа {target.chat_id} добавлена.")
    else:
        print(f"Цель {target.chat_id} уже есть — активирована.")
    return 0


def cmd_list_targets(_: argparse.Namespace) -> int:
    targets = targets_repo.list_targets()
    if not targets:
        print("Целевых групп нет.")
        return 0
    print(f"{'ID':<4} {'Активна':<8} {'chat_id':<16} {'Title'}")
    for t in targets:
        print(f"{t.id:<4} {'да' if t.is_active else 'нет':<8} "
              f"{t.chat_id:<16} {t.title or ''}")
    return 0


def cmd_add_ad_brief(args: argparse.Namespace) -> int:
    """F21 — добавить бриф нативной рекламы."""
    ads_repo.add_brief(args.brief_text, args.max_uses)
    print("✅ Бриф добавлен.")
    return 0


def cmd_list_ad_briefs(_: argparse.Namespace) -> int:
    briefs = ads_repo.list_briefs()
    if not briefs:
        print("Брифов нет.")
        return 0
    print(f"{'ID':<4} {'Акт':<4} {'Использован':<14} {'Лимит':<8} Текст")
    for b in briefs:
        preview = b.brief_text[:60].replace("\n", " ")
        limit = str(b.max_uses) if b.max_uses is not None else "∞"
        print(f"{b.id:<4} {'да' if b.is_active else 'нет':<4} "
              f"{b.times_used:<14} {limit:<8} {preview}")
    return 0


def cmd_disable_ad_brief(args: argparse.Namespace) -> int:
    if not ads_repo.disable_brief(args.brief_id):
        print(f"Бриф #{args.brief_id} не найден.")
        return 1
    print(f"✅ Бриф #{args.brief_id} деактивирован.")
    return 0


def cmd_add_telethon_session(args: argparse.Namespace) -> int:
    """F26 — добавить дополнительную Telethon-сессию (уже сгенерированную
    через `python -m tg_repost.tools.gen_session`).

    Session string вводится ИНТЕРАКТИВНО (`getpass`), а не аргументом
    командной строки — иначе секрет, эквивалентный полному доступу к
    Telegram-аккаунту, попал бы в историю шелла (`.bash_history`/PSReadLine)
    и был бы виден в выводе `ps`/диспетчера задач на всё время выполнения
    команды (найдено при security-аудите Фазы 5+, тот же класс риска, что
    для TG_SESSION_STRING основной сессии — `tools/gen_session.py` тоже
    никогда не принимает сессию аргументом).
    """
    session_string = getpass.getpass("Session string (ввод не отображается): ")
    try:
        row = telethon_sessions_repo.add_session(args.label, session_string)
    except ValueError as exc:
        print(f"Ошибка: {exc}")
        return 1
    print(f"✅ Сессия '{row.label}' добавлена (id={row.id}). Перезапусти listener "
          f"(веб-админка → Компоненты), чтобы источники распределились с её учётом.")
    return 0


def cmd_list_telethon_sessions(_: argparse.Namespace) -> int:
    sessions = telethon_sessions_repo.list_sessions()
    if not sessions:
        print("Дополнительных сессий нет — используется только основная (TG_SESSION_STRING).")
        return 0
    print(f"{'ID':<4} {'Акт':<4} {'Метка':<20} Маска")
    for s in sessions:
        print(f"{s.id:<4} {'да' if s.is_active else 'нет':<4} {s.label:<20} {s.masked_hint}")
    return 0


def cmd_disable_telethon_session(args: argparse.Namespace) -> int:
    if not telethon_sessions_repo.deactivate_session(args.session_id):
        print(f"Сессия #{args.session_id} не найдена.")
        return 1
    print(f"✅ Сессия #{args.session_id} деактивирована. Перезапусти listener, "
          f"чтобы применить.")
    return 0


def cmd_init_db(_: argparse.Namespace) -> int:
    """Создать таблицы напрямую (для dev; в проде — alembic upgrade head)."""
    Base.metadata.create_all(engine)
    print("✅ Таблицы созданы (Base.metadata.create_all).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tg_repost.cli", description="Управление источниками")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("add-source", help="Добавить источник")
    p.add_argument("channel", help="@username или ссылка t.me")
    p.set_defaults(func=cmd_add_source)

    p = sub.add_parser("remove-source", help="Деактивировать источник")
    p.add_argument("channel")
    p.set_defaults(func=cmd_remove_source)

    p = sub.add_parser("list-sources", help="Список источников")
    p.set_defaults(func=cmd_list_sources)

    p = sub.add_parser("set-source-targets", help="F12: цели для источника")
    p.add_argument("channel", help="@username источника")
    p.add_argument("chat_ids", nargs="?", default="", help="CSV chat_id, напр. -100..,-100..")
    p.add_argument("--clear", action="store_true", help="очистить (во все активные)")
    p.set_defaults(func=cmd_set_source_targets)

    p = sub.add_parser("set-source-style", help="F15: стиль рерайта источника")
    p.add_argument("channel", help="@username источника")
    p.add_argument("style", help="default | news | opinion | instruction | humor")
    p.set_defaults(func=cmd_set_source_style)

    p = sub.add_parser("set-source-enrich", help="F16: добор источников для канала")
    p.add_argument("channel", help="@username источника")
    p.add_argument("mode", choices=["on", "off", "default"], help="on/off/default")
    p.set_defaults(func=cmd_set_source_enrich)

    p = sub.add_parser("add-target", help="Добавить целевую группу")
    p.add_argument("chat_id", type=int, help="chat_id (для каналов со знаком минус)")
    p.add_argument("--title", default=None)
    p.set_defaults(func=cmd_add_target)

    p = sub.add_parser("list-targets", help="Список целевых групп")
    p.set_defaults(func=cmd_list_targets)

    p = sub.add_parser("add-ad-brief", help="F21: добавить бриф рекламы")
    p.add_argument("brief_text", help="текст брифа (используй -- если начинается с -)")
    p.add_argument("--max-uses", type=int, default=None, dest="max_uses",
                    help="лимит показов (по умолчанию без лимита)")
    p.set_defaults(func=cmd_add_ad_brief)

    p = sub.add_parser("list-ad-briefs", help="F21: список брифов рекламы")
    p.set_defaults(func=cmd_list_ad_briefs)

    p = sub.add_parser("disable-ad-brief", help="F21: деактивировать бриф")
    p.add_argument("brief_id", type=int)
    p.set_defaults(func=cmd_disable_ad_brief)

    p = sub.add_parser(
        "add-telethon-session",
        help="F26: добавить доп. Telethon-сессию (session string запросится интерактивно)",
    )
    p.add_argument("label", help="метка для сессии, напр. account-2")
    p.set_defaults(func=cmd_add_telethon_session)

    p = sub.add_parser("list-telethon-sessions", help="F26: список доп. Telethon-сессий")
    p.set_defaults(func=cmd_list_telethon_sessions)

    p = sub.add_parser("disable-telethon-session", help="F26: деактивировать доп. сессию")
    p.add_argument("session_id", type=int)
    p.set_defaults(func=cmd_disable_telethon_session)

    p = sub.add_parser("init-db", help="Создать таблицы (dev, без alembic)")
    p.set_defaults(func=cmd_init_db)

    return parser


def main(argv: list[str] | None = None) -> int:
    setup_logging("WARNING")
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
