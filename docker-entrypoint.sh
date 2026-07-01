#!/bin/sh
set -e

echo "Применяю миграции БД (alembic upgrade head)..."
alembic upgrade head

echo "Запускаю Telegram Content Repost System..."
exec python -m tg_repost.main
