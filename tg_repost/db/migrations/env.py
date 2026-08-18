"""Alembic environment. URL и метаданные берутся из приложения."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from tg_repost.config import get_settings
from tg_repost.db.models import Base

config = context.config

# Подставляем URL из настроек приложения (.env), а не из alembic.ini.
config.set_main_option("sqlalchemy.url", get_settings().database_url)

if config.config_file_name is not None:
    # `disable_existing_loggers=False` ОБЯЗАТЕЛЕН. По умолчанию `fileConfig`
    # выключает ВСЕ уже созданные логгеры, а не только настраивает свои. Если
    # миграции когда-нибудь запустятся внутри процесса приложения (а в тестах
    # они запускаются именно так), система после этого молчит: логгеры живы,
    # но обесточены, и поломку видно только по отсутствию строк в логе.
    # Найдено прогоном всех тестов: после тестов миграций четыре проверки,
    # ловящие сообщения в лог, переставали видеть хоть что-то.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,  # для ALTER на SQLite
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
