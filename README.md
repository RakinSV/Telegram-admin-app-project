# Telegram Content Repost System

Парсинг постов из Telegram-каналов → рерайт через OpenAI-совместимое API →
ручная модерация / авто-постинг → публикация в свои группы.

См. контекст и архитектуру в [CLAUDE.md](CLAUDE.md), бэклог фич —
[FEATURES.md](FEATURES.md), план по фазам — [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

## Статус

Реализовано: **Фаза 0** (каркас) + **Фаза 1** (MVP, F01–F10) +
**Фаза 2** (расширение, F11–F14, F17) + **Фаза 3** (качество контента, F15–F16) +
**Фаза 4** (рост и монетизация, F18, F20, F21 полностью; F19, F22 — каркас) +
**Фаза 5.1** (F23, веб-админка — фундамент: авторизация, шифрованные секреты,
хранилище настроек, read-only дашборд). Подфазы 5.2–5.4 (жизненный цикл
компонентов из админки, CRUD-страницы, живые логи) — впереди, план в
`C:\Users\Admin767\.claude\plans\spicy-noodling-eich.md`.

## Стек

Python 3.11+, Telethon (чтение), python-telegram-bot (постинг/модерация),
SQLAlchemy + Alembic + SQLite, APScheduler, pydantic-settings, OpenAI SDK,
FastAPI + uvicorn + Jinja2 (веб-админка, Фаза 5).

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
5. `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `OPENAI_MODEL` — провайдер рерайта.
6. Целевые группы публикации добавляются после инициализации БД через CLI
   (`add-target`, см. ниже) — отдельной настройки в `.env` для этого нет.

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

## Управление рекламными брифами (F21)

```bash
python -m tg_repost.cli add-ad-brief "Скидка 20% у партнёра XYZ" --max-uses 5
python -m tg_repost.cli list-ad-briefs
python -m tg_repost.cli disable-ad-brief 1
```

> Целевые группы хранятся только в БД (таблица `target_groups`) и
> добавляются исключительно через `add-target` — без этого шага публиковать
> посты будет некуда.

## Проверка Telethon (критерий готовности Фазы 0)

```bash
python -m tg_repost.tools.check_telethon
```
Печатает первые диалоги — подтверждение, что юзер-сессия живая.

## Запуск

```bash
python -m tg_repost.main
```
Поднимает веб-админку на http://127.0.0.1:8000 — **всегда, сразу**, даже без
заполненного `.env` (нужен только `database_url`, у него есть дефолт).
Telethon listener / бот модерации / планировщик стартуют **только если**
заданы все обязательные секреты (`TG_API_ID`, `TG_API_HASH`, `TG_BOT_TOKEN`,
`TG_OWNER_USER_ID`, `OPENAI_API_KEY`) — либо через `.env`, либо через
веб-визард `/setup`. Если не хватает — в логе подсказка открыть `/setup`,
процесс не падает.

Когда всё запущено: новый пост в источнике → рерайт → приходит в бот
владельцу с кнопками ✅/❌/✏️ → при одобрении публикуется в целевые группы.

## Веб-админка (F23, Фаза 5.1)

Встроена в тот же процесс, что и `main.py` (НЕ отдельный сервис) —
http://127.0.0.1:8000, доступ только с localhost/VPN (без TLS, по дизайну).

**Первый запуск**: открой `/setup` — создашь пароль администратора и
(опционально сразу) минимум секретов. Telethon-сессию пока нужно сгенерировать
в терминале (`python -m tg_repost.tools.gen_session`) и вставить строку в
форму — визард генерации session string прямо в браузере появится в Фазе 5.2.
Всё, что оставишь пустым на `/setup`, можно заполнить позже на `/secrets`.

**Секреты** (`/secrets`) — write-only: новое значение шифруется (`Fernet`,
ключ `WEBUI_MASTER_KEY` автогенерируется в `.env` при первом сохранении
секрета) и сохраняется, расшифрованное значение никогда не возвращается в
браузер — только маска (`••••a1b2`). ⚠️ Потеря `WEBUI_MASTER_KEY` =
зашифрованные в БД секреты невосстановимы — бэкапь `.env` вместе с БД.

**Настройки** (`/settings`) — ~25 нечувствительных полей `Settings`,
сгруппированные по фиче (F03/F11/F13/F14/F15/F16/F18/F19/F20/F21/F22).
Большинство применяется сразу (live), без перезапуска процесса. Поля с
пометкой `resync` меняют состав/расписание задач планировщика — в 5.1
сохраняются, но реально применяются только после ручного перезапуска
процесса (кнопка живого resync — Фаза 5.2).

**Дашборд** (`/`) — воронка постов по статусам, токены рерайта за сегодня,
доля FAILED за 24ч, последние посты, статус компонентов (listener/бот/
планировщик запущены или нет).

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

## Авто-обложки (F18)

`ENABLE_AUTO_COVER=true` — если у поста нет своего медиа, LLM формулирует
короткий запрос по теме и генерирует обложку:
- `COVER_STRATEGY=unsplash` (по умолчанию) — стоковое фото по ключевым словам
  через Unsplash API (`UNSPLASH_ACCESS_KEY`), быстро и бесплатно, но не уникально.
- `COVER_STRATEGY=comfyui` — уникальная AI-генерация через локальный ComfyUI.
  Нужен `COMFYUI_WORKFLOW_PATH` (экспорт workflow в API-формате: Settings →
  Enable Dev mode → Save (API Format)) и `COMFYUI_POSITIVE_NODE_ID` — id узла
  CLIPTextEncode в этом JSON, куда подставляется промпт. Эти два параметра
  специфичны для конкретной установки (чекпойнт/сэмплер) — общего шаблона нет.

Любая ошибка/не настроено → пост рерайтится без обложки, пайплайн не ломается.

## Умное расписание — каркас (F19)

Команда бота `/best_times` анализирует накопленную статистику просмотров
(F14) и **рекомендует** часы публикации — но НЕ применяет их автоматически к
`POSTING_SLOTS` (для надёжного вывода нужно реальное накопление: минимум
`SMART_SCHEDULE_MIN_POSTS` опубликованных постов за `SMART_SCHEDULE_WINDOW_DAYS`
дней). При недостатке данных команда честно сообщает об этом, а не выдаёт
случайный результат. Час считается в UTC (без поправки на таймзону аудитории).

## Авто-дайджест (F20)

`DIGEST_ENABLED=true` — раз в неделю (`DIGEST_DAY_OF_WEEK`/`DIGEST_HOUR`/
`DIGEST_MINUTE`) отбирает топ-`DIGEST_TOP_N` постов по просмотрам за
`DIGEST_WINDOW_DAYS` дней, просит LLM собрать их в один сводный пост и ставит
его в обычный пайплайн модерации/публикации (помечен «📰 ДАЙДЖЕСТ» в превью).

## Нативная реклама (F21)

`AD_EVERY_NTH_POST=N` (0 = выключено) — каждый N-й опубликованный обычный
пост в очереди сопровождается рекламным, сгенерированным ИИ из активного
брифа (round-robin по наименее использованному, см. `add-ad-brief` выше).
Рекламный пост идёт по тому же пайплайну модерации/публикации, помечен
«🎯 РЕКЛАМА» в превью. Промпт требует явной маркировки рекламы в тексте.

## Growth-трекер — каркас (F22)

`GROWTH_TRACKING_ENABLED=true` — раз в `GROWTH_SNAPSHOT_INTERVAL_MINUTES`
снимает число подписчиков активных целевых каналов через Telethon в
`channel_growth_snapshots`. Команда бота `/growth` показывает прирост за
`GROWTH_REPORT_WINDOW_DAYS` дней и количество постов по стилям за тот же
период — это **счётчики, не статистическая корреляция**: на малом объёме
данных вычислять псевдо-корреляцию было бы вводящим в заблуждение. Полноценная
корреляционная модель — следующий шаг, когда данных накопится достаточно.

## Тесты

```bash
pytest
```

## Структура

```
tg_repost/
  config.py            # pydantic Settings + оверлей из БД (F23, Фаза 5)
  crypto.py            # Fernet-шифрование секретов at rest (F23)
  logging_conf.py      # логирование (F10)
  retry.py             # ретрай сетевых вызовов
  antiban.py           # джиттер + почасовой лимит (F17)
  filtering.py         # фильтр ключевых слов (F03)
  cli.py               # источники/цели/стили/брифы (F01, F12, F15, F16, F21)
  main.py              # точка входа: веб-сервер + условный старт Telegram-части
  webui/                # веб-админка (F23, Фаза 5.1)
    app.py               # FastAPI app: /setup /login /settings /secrets /
    auth.py              # пароль (Argon2id), сессии, require_login
    settings_store.py    # запись настроек/секретов, SETTINGS_GROUPS
    dashboard.py          # query-функции для дашборда
    runtime_state.py      # статус компонентов для дашборда
    templates/, static/   # Jinja2-шаблоны, минимальный CSS
  db/
    models.py          # ORM, статус-машина (F05), PostKind (F18-F21), post_stats (F14),
                        # AppSetting/Secret/AdminUser/AuditLog (F23)
    session.py
    migrations/        # alembic (0001..0005)
  telegram/
    listener.py        # Telethon listener (F02-F04, F13, F17)
    publisher.py       # публикация (F08), per-source цели (F12)
    moderation_bot.py  # модерация (F07), /stats /best_times /growth
  rewriter/
    client.py          # OpenAI-клиент: рерайт+стили (F06/F15), complete (F16/F18/F20/F21), эмбеддинги (F13)
    prompts/           # default/news/opinion/instruction/humor, keywords, select_sources,
                        # cover_prompt (F18), digest (F20), native_ad (F21)
  dedup/
    hash_dedup.py      # хэш-дедуп (F04)
    semantic.py        # семантический дубль-чек (F13)
  enrichment/
    search.py          # клиент Brave Search (F16)
    enricher.py        # оркестрация добора источников (F16)
  covers/
    unsplash.py        # клиент Unsplash (F18)
    comfyui.py          # клиент локального ComfyUI (F18)
    dispatcher.py       # выбор стратегии, сохранение файла (F18)
  ads/
    injector.py         # периодичность + генерация рекламного поста (F21)
  scheduler/
    jobs.py             # рерайт-джоба (стиль+обогащение+обложка+реклама), пайплайн-тик
    posting.py          # авто-постинг по слотам (F11)
    stats.py            # сбор статистики (F14)
    digest.py           # авто-дайджест недели (F20)
    smart_schedule.py   # рекомендация часов публикации, каркас (F19)
    growth.py           # снимки подписчиков + отчёт, каркас (F22)
  tools/
    gen_session.py     # генерация Telethon session string
    check_telethon.py  # диагностика авторизации
tests/                 # unit-тесты на все фичи F01-F23 (чистые функции + БД)
```
