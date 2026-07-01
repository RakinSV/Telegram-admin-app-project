#!/bin/sh
set -e

echo "Применяю миграции Guardian (alembic -c alembic_guardian.ini upgrade head)..."
alembic -c alembic_guardian.ini upgrade head

echo "Запускаю Guardian..."
exec python -m guardian.bot
