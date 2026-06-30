"""CLI управления источниками и целевыми группами (F01).

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
import sys

from tg_repost.db.models import AdBrief, Base, Source, TargetGroup
from tg_repost.db.session import engine, session_scope
from tg_repost.logging_conf import setup_logging


def _normalize_username(raw: str) -> str:
    """Привести @name / https://t.me/name к виду 'name'."""
    raw = raw.strip()
    raw = raw.removeprefix("https://t.me/").removeprefix("t.me/")
    raw = raw.lstrip("@")
    return raw


def cmd_add_source(args: argparse.Namespace) -> int:
    username = _normalize_username(args.channel)
    with session_scope() as session:
        existing = (
            session.query(Source).filter(Source.channel_username == username).one_or_none()
        )
        if existing:
            existing.is_active = True
            print(f"Источник @{username} уже есть — активирован.")
            return 0
        session.add(Source(channel_username=username, is_active=True))
    print(f"✅ Источник @{username} добавлен.")
    return 0


def cmd_remove_source(args: argparse.Namespace) -> int:
    username = _normalize_username(args.channel)
    with session_scope() as session:
        source = (
            session.query(Source).filter(Source.channel_username == username).one_or_none()
        )
        if source is None:
            print(f"Источник @{username} не найден.")
            return 1
        source.is_active = False
    print(f"✅ Источник @{username} деактивирован.")
    return 0


def cmd_list_sources(_: argparse.Namespace) -> int:
    with session_scope() as session:
        sources = session.query(Source).order_by(Source.id).all()
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

    username = _normalize_username(args.channel)
    style = args.style.strip().lower()
    if not prompt_exists(style):
        print(f"Неизвестный стиль '{style}'. Доступны: {', '.join(KNOWN_STYLES)}")
        return 1
    with session_scope() as session:
        source = (
            session.query(Source).filter(Source.channel_username == username).one_or_none()
        )
        if source is None:
            print(f"Источник @{username} не найден.")
            return 1
        source.style_profile = style
    print(f"✅ Источник @{username} → стиль '{style}'")
    return 0


def cmd_set_source_enrich(args: argparse.Namespace) -> int:
    """F16 — включить/выключить добор источников для канала."""
    username = _normalize_username(args.channel)
    mapping = {"on": True, "off": False, "default": None}
    value = mapping[args.mode]
    with session_scope() as session:
        source = (
            session.query(Source).filter(Source.channel_username == username).one_or_none()
        )
        if source is None:
            print(f"Источник @{username} не найден.")
            return 1
        source.enrich_sources = value
    human = {"on": "включён", "off": "выключен", "default": "по глобальной настройке"}
    print(f"✅ Добор источников для @{username}: {human[args.mode]}")
    return 0


def cmd_set_source_targets(args: argparse.Namespace) -> int:
    """F12 — задать/очистить переопределение целей для источника."""
    username = _normalize_username(args.channel)
    with session_scope() as session:
        source = (
            session.query(Source).filter(Source.channel_username == username).one_or_none()
        )
        if source is None:
            print(f"Источник @{username} не найден.")
            return 1
        if args.clear:
            source.target_chat_ids = None
            print(f"✅ Переопределение целей для @{username} очищено (идёт во все).")
            return 0
        # Валидируем, что переданы числа.
        ids = [c.strip() for c in args.chat_ids.split(",") if c.strip()]
        for c in ids:
            int(c)  # бросит ValueError при мусоре
        source.target_chat_ids = ",".join(ids)
    print(f"✅ Источник @{username} → цели {args.chat_ids}")
    return 0


def cmd_add_target(args: argparse.Namespace) -> int:
    with session_scope() as session:
        existing = (
            session.query(TargetGroup)
            .filter(TargetGroup.chat_id == args.chat_id)
            .one_or_none()
        )
        if existing:
            existing.is_active = True
            if args.title:
                existing.title = args.title
            print(f"Цель {args.chat_id} уже есть — активирована.")
            return 0
        session.add(TargetGroup(chat_id=args.chat_id, title=args.title, is_active=True))
    print(f"✅ Целевая группа {args.chat_id} добавлена.")
    return 0


def cmd_list_targets(_: argparse.Namespace) -> int:
    with session_scope() as session:
        targets = session.query(TargetGroup).order_by(TargetGroup.id).all()
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
    with session_scope() as session:
        session.add(
            AdBrief(brief_text=args.brief_text, is_active=True, max_uses=args.max_uses)
        )
    print("✅ Бриф добавлен.")
    return 0


def cmd_list_ad_briefs(_: argparse.Namespace) -> int:
    with session_scope() as session:
        briefs = session.query(AdBrief).order_by(AdBrief.id).all()
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
    with session_scope() as session:
        brief = session.get(AdBrief, args.brief_id)
        if brief is None:
            print(f"Бриф #{args.brief_id} не найден.")
            return 1
        brief.is_active = False
    print(f"✅ Бриф #{args.brief_id} деактивирован.")
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
