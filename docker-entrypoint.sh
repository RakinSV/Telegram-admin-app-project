#!/bin/sh
set -e

echo "Применяю миграции БД (alembic upgrade head)..."
alembic upgrade head

# Веб-админка этого процесса читает БД Guardian НАПРЯМУЮ (webui/guardian_routes.py,
# кросс-пакетный импорт) — без этого шага /guardian* падает "no such table",
# если этот контейнер стартует раньше/быстрее контейнера guardian (нет
# depends_on между сервисами в docker-compose.yml, оба стартуют параллельно).
# Идемпотентно (alembic_version) — безопасно гонять из обоих контейнеров.
echo "Применяю миграции Guardian (alembic -c alembic_guardian.ini upgrade head)..."
alembic -c alembic_guardian.ini upgrade head

echo "Запускаю Telegram Content Repost System..."
exec python -m tg_repost.main
