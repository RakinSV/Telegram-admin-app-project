# Telegram Content Repost System

Парсинг постов из Telegram-каналов → рерайт через OpenAI-совместимое API →
ручная модерация / авто-постинг → публикация в свои группы.

См. контекст и архитектуру в [CLAUDE.md](CLAUDE.md), бэклог фич —
[FEATURES.md](FEATURES.md), план по фазам — [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

## Статус

Реализовано: **Фаза 0** (каркас) + **Фаза 1** (MVP, F01–F10) +
**Фаза 2** (расширение, F11–F14, F17) + **Фаза 3** (качество контента, F15–F16).

## Стек

Python 3.11+, Telethon (чтение), python-telegram-bot (постинг/модерация),
SQLAlchemy + Alembic + SQLite, APScheduler, pydantic-settings, OpenAI SDK.

## Установка

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# bash:
# source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # затем заполнить значения
```

## Настройка `.env`

1. `TG_API_ID` / `TG_API_HASH` — получить на https://my.telegram.org.
2. Сгенерировать session string для Telethon:
   ```bash
   python -m tg_repost.tools.gen_session
   ```
   Вставить вывод в `TG_SESSION_STRING`.
3. `TG_BOT_TOKEN` — создать бота у @BotFather.
4. `TG_OWNER_USER_ID` — свой user_id (узнать у @userinfobot).
5. `TG_TARGET_CHAT_ID` — chat_id целевой группы/канала (бот должен быть админом).
6. `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `OPENAI_MODEL` — провайдер рерайта.

## Инициализация БД

```bash
# Через alembic (рекомендуется):
alembic upgrade head

# Или быстро для dev (без миграций):
python -m tg_repost.cli init-db
```

## Управление источниками и целями (F01, F12)

```bash
python -m tg_repost.cli add-source @some_channel
python -m tg_repost.cli list-sources
python -m tg_repost.cli remove-source @some_channel

python -m tg_repost.cli add-target -1001234567890 --title "Мой канал"
python -m tg_repost.cli list-targets

# F12: публиковать посты источника только в выбранные группы.
# chat_id отрицательные, поэтому нужен разделитель "--":
python -m tg_repost.cli set-source-targets @some_channel -- -1001111,-1002222
python -m tg_repost.cli set-source-targets @some_channel --clear   # снова во все

# F15: стиль рерайта для источника (default|news|opinion|instruction|humor):
python -m tg_repost.cli set-source-style @some_channel news

# F16: добор источников для источника (on|off|default=по глобальной настройке):
python -m tg_repost.cli set-source-enrich @some_channel on
```

> `TG_TARGET_CHAT_ID` из `.env` — это значение по умолчанию для первого
> запуска; целевые группы хранятся в БД и добавляются через `add-target`.

## Проверка Telethon (критерий готовности Фазы 0)

```bash
python -m tg_repost.tools.check_telethon
```
Печатает первые диалоги — подтверждение, что юзер-сессия живая.

## Запуск

```bash
python -m tg_repost.main
```
Запускает listener + бот модерации + пайплайн-тик. Новый пост в источнике →
рерайт → приходит в бот владельцу с кнопками ✅/❌/✏️ → при одобрении
публикуется в целевые группы.

## Режимы публикации (Фаза 2)

Два независимых флага в `.env`:

- `AUTO_POST_ENABLED=true` — без ручной модерации: рерайченные посты сразу
  одобряются (кнопки не присылаются).
- `SCHEDULED_POSTING_ENABLED=true` (F11) — одобренные посты не публикуются
  мгновенно, а встают в очередь и выходят по слотам `POSTING_SLOTS`
  (например `10:00,14:00,19:00`), по `POSTING_BATCH_PER_SLOT` за слот.

Комбинации: ручная модерация + мгновенно (оба false); ручная модерация +
дрип по слотам (только scheduled); полный автопилот по слотам (оба true).

## Семантический дубль-чек (F13)

`SEMANTIC_DEDUP_ENABLED=true` — кроме хэша (F04) ловит перефразированные
повторы через эмбеддинги (`OPENAI_EMBEDDING_MODEL`) и косинусное сходство
выше `SEMANTIC_SIMILARITY_THRESHOLD` за окно `DEDUP_WINDOW_DAYS`.
⚠️ Тратит токены на каждый пост — по умолчанию выключено.

## Статистика (F14)

`STATS_ENABLED=true` — раз в `STATS_INTERVAL_MINUTES` собирает просмотры/
пересылки/реакции опубликованных постов через Telethon в таблицу `post_stats`.
Команда бота `/stats` — сводка за `STATS_WINDOW_DAYS` дней.

## Антибан (F17)

Джиттер между обработкой постов (`LISTENER_MIN/MAX_DELAY_SECONDS`) и почасовой
лимит «тяжёлых» действий (`MAX_READS_PER_HOUR`) — снижают риск ограничений
юзер-сессии Telethon.

## Стиль-профили рерайта (F15)

Промпт-шаблоны под тип контента в `rewriter/prompts/`: `default`, `news`,
`opinion`, `instruction`, `humor`. Привязка к источнику —
`set-source-style @channel news`; профиль по умолчанию — `DEFAULT_STYLE_PROFILE`.
Промпты в отдельных файлах, меняются без передеплоя кода.

## Добор источников (F16)

`ENABLE_SOURCE_ENRICHMENT=true` + `BRAVE_API_KEY` — при рерайте система через
LLM выделяет поисковый запрос, ищет в Brave Search, LLM отбирает до
`ENRICHMENT_MAX_SOURCES` релевантных результатов и добавляет в конец поста блок
«📚 Источники:» с разделением на русско- и англоязычные. Per-source:
`set-source-enrich @channel on|off|default`. При любой ошибке/отсутствии ключа
пост рерайтится без блока — пайплайн не ломается.

## Тесты

```bash
pytest
```

## Структура

```
tg_repost/
  config.py            # pydantic Settings
  logging_conf.py      # логирование (F10)
  retry.py             # ретрай сетевых вызовов
  antiban.py           # джиттер + почасовой лимит (F17)
  filtering.py         # фильтр ключевых слов (F03)
  cli.py               # управление источниками/целями (F01, F12)
  main.py              # точка входа
  db/
    models.py          # ORM + статус-машина (F05), post_stats (F14)
    session.py
    migrations/        # alembic (0001 + 0002 + 0003)
  telegram/
    listener.py        # Telethon listener (F02-F04, F13, F17)
    publisher.py       # публикация (F08), per-source цели (F12)
    moderation_bot.py  # модерация (F07), /stats (F14)
  rewriter/
    client.py          # OpenAI-клиент: рерайт+стили (F06/F15), complete (F16), эмбеддинги (F13)
    prompts/           # default, news, opinion, instruction, humor, keywords, select_sources
  dedup/
    hash_dedup.py      # хэш-дедуп (F04)
    semantic.py        # семантический дубль-чек (F13)
  enrichment/
    search.py          # клиент Brave Search (F16)
    enricher.py        # оркестрация добора источников (F16)
  scheduler/
    jobs.py            # рерайт-джоба (стиль+обогащение), пайплайн-тик
    posting.py         # авто-постинг по слотам (F11)
    stats.py           # сбор статистики (F14)
  tools/
    gen_session.py     # генерация Telethon session string
    check_telethon.py  # диагностика авторизации
tests/                 # unit-тесты (F03/F04/F05/F11/F12/F13/F15/F16/F17)
```
