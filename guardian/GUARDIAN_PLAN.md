# Guardian Bot — план реализации

> Независимый план от IMPLEMENTATION_PLAN.md репост-бота.
> Можно делать параллельно или после фазы 1 репост-бота.
> Guardian — самостоятельный сервис, добавляется в общий docker-compose.

---

## Фаза G0 — Подготовка

1. Создать отдельного бота через @BotFather → GUARDIAN_BOT_TOKEN.
2. Добавить бота в целевую группу как администратора с правами:
   - Удаление сообщений
   - Блокировка пользователей
   - Ограничение прав участников
3. Создать приватный канал для логов модерации, добавить туда бота.
   Получить GUARDIAN_LOG_CHANNEL_ID (через @userinfobot или API).
4. Структура файлов (создать пустые `__init__.py`):
   ```
   guardian/
     __init__.py
     config.py
     bot.py
     db/ handlers/ filters/ services/
     prompts/
       spam_classifier.txt
     data/
       stopwords_default.txt
       allowed_domains.txt
   ```
5. `guardian/config.py` — GuardianSettings(BaseSettings), все env vars
   из GUARDIAN.md секция «Переменные окружения».
6. Обновить `.env.example` — добавить все GUARDIAN_* переменные.
7. Обновить `docker-compose.yml` — добавить сервис `guardian`:
   ```yaml
   guardian:
     build: .
     container_name: tg_guardian
     restart: unless-stopped
     env_file: .env
     command: python -m guardian.bot
     volumes:
       - ./data:/app/data
       - ./guardian/prompts:/app/guardian/prompts
       - ./guardian/data:/app/guardian/data
   ```
   Один Dockerfile на оба сервиса (общий Python-образ), разные `command`.

**Критерий готовности**: `docker-compose up guardian` запускается,
бот онлайн в Telegram, `/start` или любая команда — ответ получен.

---

## Фаза G1 — MVP: верификация + стоп-слова + варны

**Фичи: G01, G02, G03, G04, G05, G06, G07, G08**

### Порядок реализации:

**1. Модели БД** (`guardian/db/models.py`):
```python
class Member:
    user_id, chat_id, username, first_name
    join_date, is_verified, warn_count
    last_warn_date, is_trusted, is_banned

class Warning:
    id, user_id, chat_id, reason, created_at, issued_by (user или 'auto')

class StopWord:
    id, word, added_by, added_at

class TrustedUser:
    user_id, chat_id, added_by, added_at, reason

class ModerationLog:
    id, action (warn/mute/kick/ban/delete_msg), user_id, chat_id
    reason, details, created_at, actor (user_id или 'auto')

class BotConfig:
    key, value, updated_by, updated_at

class DailyStats:
    date, chat_id, deleted_msgs, warnings, mutes, kicks, bans
    new_members, verified_members, ai_calls, ai_cost_usd
```
Alembic-миграция: создать все таблицы.

**2. `guardian/services/captcha.py`**:
```python
async def generate_captcha(captcha_type: str) -> tuple[str, str]:
    # возвращает (вопрос, правильный_ответ)
    if captcha_type == 'math':
        a, b = random.randint(1,9), random.randint(1,9)
        return f"Сколько будет {a} + {b}?", str(a+b)
    elif captcha_type == 'button':
        return "Нажми кнопку ниже:", "verified"
    elif captcha_type == 'question':
        # загрузить из bot_config таблицы, выбрать случайный
        ...

async def make_captcha_keyboard(captcha_type, correct_answer):
    # для math: 4 варианта кнопок (1 правильный + 3 случайных)
    # для button: одна кнопка «Я не робот»
    ...
```

**3. `guardian/handlers/join.py`** (FSM):
```python
class CaptchaStates(StatesGroup):
    waiting_answer = State()

@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def on_new_member(event, bot, state, session):
    # 1. restrict_chat_member (can_send_messages=False)
    # 2. generate_captcha()
    # 3. отправить сообщение с вопросом + клавиатурой
    # 4. set_state(CaptchaStates.waiting_answer)
    # 5. сохранить {user_id: (correct_answer, message_id, timeout_job_id)}
    # 6. запланировать кик через CAPTCHA_TIMEOUT_MINUTES (APScheduler)
    # 7. записать в members (is_verified=False)

@router.callback_query(CaptchaStates.waiting_answer)
async def on_captcha_answer(callback, bot, state, session):
    # проверить ответ
    # правильно → restrict(all=True), удалить капча-сообщение,
    #              отправить приветствие (удалить через 120с), is_verified=True
    # неправильно → ещё одна попытка или кик (конфиг)
    # отменить scheduled кик если ответил правильно
```

**4. `guardian/filters/keyword_filter.py`**:
```python
class KeywordFilter:
    def __init__(self, session): ...
    
    async def reload(self):
        # загрузить стоп-слова из БД в память (set для O(1) поиска)
        
    def normalize(self, text: str) -> str:
        # lowercase, убрать дубли пробелов
        # заменить: а→а, е→е, о→о (латинские на кириллические)
        # убрать Zero-Width символы
        # убрать спецсимволы между буквами (к-у-п-и-т-ь → купить)
        
    def check(self, text: str) -> tuple[bool, str | None]:
        # вернуть (is_spam, matched_word)
```

**5. `guardian/filters/link_filter.py`**:
```python
class LinkFilter:
    LINK_PATTERN = re.compile(r'https?://|t\.me/|www\.')
    
    def check(self, message) -> bool:
        # проверить text и entities (type=text_link)
        # для каждой ссылки извлечь домен
        # если домен не в allowed_domains → spam
```

**6. `guardian/handlers/messages.py`**:
```python
@router.message(F.chat.type.in_({'group', 'supergroup'}))
async def on_message(message, session, warn_system, settings):
    user_id = message.from_user.id
    
    # 0. trusted? → пропустить всё
    if await is_trusted(user_id, session): return
    
    # 1. flood check
    if flood_filter.check(user_id): → warn + удалить
    
    # 2. link check
    if link_filter.check(message): → удалить + warn
    
    # 3. keyword check (режим keywords или hybrid)
    if settings.spam_mode in ('keywords', 'hybrid'):
        hit, word = keyword_filter.check(message.text)
        if hit: → удалить + warn (reason=f'стоп-слово: {word}')
    
    # 4. ai check (режим ai или hybrid с подозрительным сообщением)
    if нужно_ai_check: → await ai_filter.check(message.text) → действие
```

**7. `guardian/services/warn_system.py`** — реализовать эскалацию (см. G05).

**8. `guardian/services/log_channel.py`**:
```python
async def log_action(bot, action, user, reason, message_text=None, inline_kb=None):
    emoji = {'warn':'⚠️','mute':'🔇','kick':'👢','ban':'🔴','delete':'🗑️'}
    text = f"{emoji[action]} [{action.upper()}] @{user.username}\n..."
    await bot.send_message(LOG_CHANNEL_ID, text, reply_markup=inline_kb)
```

**9. `guardian/handlers/admin.py`** — команды /warn /mute /ban /kick /unban
/check /addword /delword /trust /untrust с проверкой is_admin().

**Критерий готовности фазы G1**: 
- Новый участник получает капчу, не ответил → кик.
- Сообщение со стоп-словом → удаляется + варн в чат.
- 3 варна → мут, 4 → бан (или по конфигу).
- Лог-канал получает уведомления о каждом действии.
- Команды администратора работают.

---

## Фаза G2 — AI-фильтр и расширенные функции

**Фичи: G09, G10, G11, G12, G13**

1. **G09 — AI-классификатор** (`guardian/filters/ai_filter.py`):
   Использовать тот же `openai`-клиент что в рерайтере (те же OPENAI_*
   env vars). Отдельный метод с таймаутом 3с и try/except — при ошибке
   API пропускать сообщение (не удалять), логировать ошибку.

2. **G10 — Гибридный режим**: обновить `messages.py` логикой подозрительности
   (см. GUARDIAN_FEATURES.md G10).

3. **G11 — /stats**: агрегация из moderation_log + daily_stats. Текстовый
   форматированный ответ с emoji-иконками.

4. **G12 — Trusted**: автодоверие через APScheduler (ежедневная джоба).
   Добавить REPOST_BOT_ID в trusted при старте `guardian/bot.py`.

5. **G13 — Конфиг через команды**: обновить admin.py командами /setmode
   /setwarn /setcaptcha и т.д. Кеш конфига в памяти с инвалидацией
   при записи в БД.

**Критерий готовности**: режим можно переключить командой без перезапуска,
AI-фильтр работает в гибридном режиме, репост-бот в whitelist.

---

## Фаза G3 — Продвинутая защита

**Фичи: G14, G15, G16, G17**

1. **G14 — Антирейд**: APScheduler-джоба каждую минуту. Тест: запустить
   несколько аккаунтов вступить одновременно (тестовая группа).

2. **G15 — Анализ профиля**: hook в `join.py` перед капчей.
   Scoring: чем выше score → строже капча или автомут.

3. **G16 — Режимы строгости**: два профиля в bot_config, расписание.

4. **G17 — /growth**: агрегация daily_stats, текстовый спарклайн.

---

## Интеграция в общий docker-compose.yml

Финальный `docker-compose.yml` с обоими сервисами:

```yaml
services:
  repost:
    build: .
    container_name: tg_repost_app
    restart: unless-stopped
    env_file: .env
    command: python -m tg_repost.main
    volumes:
      - ./data:/app/data
      - ./media:/app/media
      - ./tg_repost/rewriter/prompts:/app/tg_repost/rewriter/prompts

  guardian:
    build: .
    container_name: tg_guardian
    restart: unless-stopped
    env_file: .env
    command: python -m guardian.bot
    volumes:
      - ./data:/app/data          # общая БД или отдельная — через конфиг
      - ./guardian/prompts:/app/guardian/prompts
      - ./guardian/data:/app/guardian/data
    depends_on:
      - repost                    # guardian стартует после repost (опционально)
```

Один `docker-compose up -d --build` поднимает ОБА бота.
