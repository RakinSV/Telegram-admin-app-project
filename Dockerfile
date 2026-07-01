FROM python:3.11-slim

# Однопользовательский внутренний инструмент (F27 явно отклонён — только свои
# каналы), контейнер доступен только через localhost/VPN-проброс порта
# (см. docker-compose.yml) — поэтому осознанно запускаем от root, не заводя
# отдельного пользователя: это убирает необходимость chown/gosu-логики в
# entrypoint для примонтированных volume'ов (частый источник permission-багов
# при SQLite + bind mount).

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tg_repost ./tg_repost
COPY guardian ./guardian
COPY alembic.ini alembic_guardian.ini .
COPY docker-entrypoint.sh docker-entrypoint-guardian.sh .
RUN chmod +x docker-entrypoint.sh docker-entrypoint-guardian.sh

EXPOSE 8000

# Один образ, два сервиса (см. docker-compose.yml): tg_repost использует
# ENTRYPOINT по умолчанию, guardian переопределяет его на
# docker-entrypoint-guardian.sh — общий Dockerfile, разный процесс.
ENTRYPOINT ["./docker-entrypoint.sh"]
