"""Конфигурация приложения через pydantic-settings.

Базовые значения читаются из `.env` (см. `.env.example`). С Фазы 5 (F23,
веб-админка) `get_settings()` дополнительно накладывает оверлей: настройки
из таблицы `app_settings` и расшифрованные секреты из таблицы `secrets`
(см. `_apply_db_overrides`/`_apply_secret_overrides` ниже) — так веб-панель
может менять конфигурацию без правки `.env` руками. 30+ существующих мест
вызова `get_settings()` по коду не меняются: оверлей полностью прозрачен.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "rewriter" / "prompts"


def _prompt_file_default(name: str) -> str:
    """Стартовое значение промпт-настройки — из файла `rewriter/prompts/`.

    Файлы остаются источником истины для ДЕФОЛТОВ (их удобно править в git и
    видеть в diff), а поле настройки даёт админке возможность переопределить
    промпт без передеплоя. Читается напрямую, а не через
    `rewriter.client.load_prompt()`: тот импортирует config.py, вышел бы
    циклический импорт.

    Отсутствие файла не должно ронять весь процесс на старте (`Settings()`
    конструируется раньше всего остального) — пустой дефолт означает, что
    `resolve_rewrite_template()` откатится на `default`.
    """
    try:
        return (_PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Не прочитан файл промпта %s.txt: %s", name, exc)
        return ""

# Дефолты ВСЕХ пяти промптов рерайта лежат в `rewriter/prompts/*.txt` — там же,
# где запасные варианты на случай очищенного поля в админке. Раньше промпт
# стиля "default" дублировался ещё и литералом здесь, и две копии успели
# разойтись: в файле остался старый слабый текст («перепиши так, чтобы было
# уникально по формулировкам»), а в литерале — новый. Очистка поля в админке
# откатывала пользователя на СТАРУЮ редакцию, и заметить это было нечем.
#
# Плейсхолдеры в шаблонах: `{post_text}` — исходный пост из Telegram,
# `{link_content}` — текст статьи по ссылке (пусто, если ссылки не было или
# переход не удался, см. `enrichment/link_content.py`). Оба подставляются
# всегда: `str.format()` просто не использует неупомянутый в шаблоне аргумент,
# так что пользователь может убрать любой из них в своей версии текста.

# Анти-ИИ блок (F15-доп.) — приклеивается к ЛЮБОМУ промпту рерайта, когда
# включён `rewrite_humanize_enabled`. Отдельно от самих стиль-промптов
# намеренно: правило "не звучи как нейросеть" одинаково для новости, мнения
# и юмора, дублировать его в пяти шаблонах — гарантированно разъехавшиеся
# копии. Список ниже — не абстрактное "пиши живее", а конкретные маркеры
# LLM-текста, которые и делают рерайт узнаваемо машинным.
_DEFAULT_HUMANIZE_INSTRUCTIONS = """ЖИВОЙ ТЕКСТ (обязательно)
Готовый пост не должен читаться как написанный нейросетью. Конкретно:

- Ритм. Меняй длину предложений: короткое рядом с длинным. Ровный ряд фраз
  одинаковой длины — главный признак машинного текста.
- Запрещённые конструкции:
  «не просто X, а Y» · «это не только X, но и Y» · «в мире, где»
  «давайте разберёмся» · «важно понимать, что» · «речь идёт о том, что»
- Запрещённые связки:
  «стоит отметить» · «следует подчеркнуть» · «таким образом» · «более того»
  «в заключение» · «подводя итог» · «резюмируя» · «не секрет, что»
- Никаких перечислений тройками ради ритма («быстро, дёшево и надёжно»).
- Не открывай пост риторическим вопросом и не закрывай выводом-моралью,
  которой не было в исходном материале.
- Не ставь эмодзи в начало каждого абзаца и не делай буллеты одинаковой
  длины с одинаковой грамматикой. Живой текст неровный.
- Не подстраховывайся: убери «возможно», «вероятно», «в некоторой степени»
  там, где в источнике сказано прямо.
- Не разжёвывай очевидное и не объясняй читателю, что он сейчас прочитает.
- Конкретика вместо обобщений: число, название и дата вместо
  «ряд экспертов» · «некоторые компании» · «в последнее время»
- Тире и двоеточия — по делу, а не как универсальный способ связать части
  фразы."""

# Дефолт для `cover_image_prompt_template` (F18-доп., стратегия "openai") —
# промпт для самого генератора картинок (не для LLM, выбирающего короткий
# search-запрос, как в cover_search_prompt_template для unsplash/comfyui).
# `{post_text}` — исходный пост, редактируется в /settings (textarea).
#
# "no text" повторено несколько раз и в начале, и в конце намеренно: модели
# генерации изображений систематически дорисовывают надписи/подписи/логотипы
# на "новостных" картинках, одного упоминания в середине промпта не хватает.
# Сцена просится АССОЦИАТИВНАЯ, а не буквальная иллюстрация заголовка —
# буквальная почти всегда вырождается в коллаж с псевдотекстом.
_DEFAULT_COVER_IMAGE_PROMPT = """A photorealistic editorial cover photograph. NO TEXT of any kind: no letters, \
no words, no numbers, no captions, no watermarks, no logos, no brand marks, \
no street signs, no book covers, no screens showing text, no UI elements.

Subject: a single clean real-world scene that a picture editor would choose to \
sit above the story below — one object, place, material detail or human \
gesture that carries the mood of the topic. Suggest the theme by association; \
never illustrate the headline literally, and never depict recognisable public \
figures or company branding.

Composition: one clear focal point, uncluttered background, generous negative \
space in the upper third so a caption could sit there, wide 16:9 framing.

Light and craft: natural directional light, shallow depth of field, realistic \
colour, no collage, no split screens, no text overlay panels.

Story (use only as a source of association, never render its words):
---
{post_text}
---

The final image must contain no readable text anywhere."""

# Дефолт для `cover_search_prompt_template` (F18) — это промпт для ТЕКСТОВОЙ
# модели, которая выдаёт короткий запрос для Unsplash/ComfyUI. Раньше лежал
# только в `rewriter/prompts/cover_prompt.txt` и не редактировался из
# админки, хотя от него напрямую зависит, что за картинка приедет.
_DEFAULT_COVER_SEARCH_PROMPT = """<пост>
{post_text}
</пост>

Подбери короткий запрос на английском (3–8 слов) для поиска или генерации
фотографии-обложки к посту выше.

- Опиши КОНКРЕТНУЮ визуальную сцену или предмет, связанный с темой по
  ассоциации. Не пересказывай заголовок: не «new tax law», а «empty office
  desk stacked paper documents».
- Только то, что можно сфотографировать: предмет, место, действие, фактура.
  Абстракции вроде «economy» или «innovation» дают мусорную выдачу.
- Ни одного слова, ведущего к тексту в кадре: без sign, poster, banner,
  headline, newspaper, magazine, screen with text, infographic, chart,
  diagram, logo.
- Без имён людей, названий компаний и брендов.
- Без слов о людях в кадре, если тема не про конкретное действие человека.

Верни ТОЛЬКО сам запрос одной строкой — без кавычек, без пояснений, без
префикса вроде «Запрос:»."""


class Settings(BaseSettings):
    """Типизированные настройки приложения."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Telegram: Telethon (юзер-сессия для чтения) ---
    # Поля ниже стали опциональными в Фазе 5: раньше их отсутствие в .env
    # ронялo Settings() целиком, не давая веб-серверу даже подняться для
    # /setup-визарда. Полнота проверяется через `is_minimally_configured`.
    tg_api_id: int = Field(0, alias="TG_API_ID")
    tg_api_hash: str = Field("", alias="TG_API_HASH")
    tg_session_string: str = Field("", alias="TG_SESSION_STRING")

    # --- Telegram: Bot API (постинг и модерация) ---
    tg_bot_token: str = Field("", alias="TG_BOT_TOKEN")
    tg_owner_user_id: int = Field(0, alias="TG_OWNER_USER_ID")
    # Целевые группы публикации (F08/F12) хранятся в таблице `target_groups`,
    # управление — только через `cli.py add-target`. Отдельной настройки
    # "целевой группы по умолчанию" в .env намеренно нет — раньше здесь было
    # неиспользуемое поле TG_TARGET_CHAT_ID, вводившее в заблуждение (выглядело
    # как рабочий конфиг, но нигде не читалось).

    # --- Прокси ---
    # MTProto-прокси — только для Telethon (юзер-сессия говорит на MTProto
    # напрямую с серверами Telegram). Один общий прокси на ВСЕ Telethon-
    # клиенты — и основной, и дополнительные из ротации сессий (F26): цель
    # обычно "спрятать IP сервера", а не развести аккаунты по разным адресам.
    # host/port не секрет сами по себе (бесполезны без secret), поэтому
    # обычные настройки; mtproto_proxy_secret — в SECRET_FIELD_NAMES ниже.
    mtproto_proxy_host: str = Field("", alias="MTPROTO_PROXY_HOST")
    mtproto_proxy_port: int = Field(0, alias="MTPROTO_PROXY_PORT")
    mtproto_proxy_secret: str = Field("", alias="MTPROTO_PROXY_SECRET")
    # SOCKS5-прокси для Telethon (юзер-сессия) — АЛЬТЕРНАТИВА MTProto-прокси
    # выше. В отличие от MTProto-прокси, это обычный TCP-туннель: Telethon
    # через него ходит НАПРЯМУЮ к настоящим серверам Telegram и говорит
    # MTProto поверх туннеля. Не имеет ограничения fake-TLS (ee-секреты),
    # которое есть у MTProto-прокси-класса Telethon (репо Telethon
    # заархивирован 02.2026, fake-TLS так и не добавили). Имеет ПРИОРИТЕТ над
    # MTPROTO_PROXY_* если задан (см. listener.py::_telethon_proxy_kwargs).
    # URL socks5://[user:pass@]host:port — целиком секрет (может нести креды).
    telethon_proxy_url: str = Field("", alias="TELETHON_PROXY_URL")
    # SOCKS5-прокси для Bot API (постинг/модерация репост-бота) — Bot API
    # ходит по HTTPS, MTProto-прокси тут не применим. Логин:пароль в URL
    # опциональны, как и у TELETHON_PROXY_URL выше — формат
    # socks5://[user:pass@]host:port. URL целиком секрет (может нести креды).
    bot_api_proxy_url: str = Field("", alias="BOT_API_PROXY_URL")

    # --- Рерайт (OpenAI-совместимое API) ---
    openai_base_url: str = Field("https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_api_key: str = Field("", alias="OPENAI_API_KEY")
    openai_model: str = Field("gpt-4o-mini", alias="OPENAI_MODEL")
    # Промпты рерайта — ВСЕ пять стилей (F15) редактируются прямо в /settings.
    # Раньше поле было только у "default", а news/opinion/instruction/humor
    # читались напрямую из файлов: источник со `style_profile="news"` молча
    # игнорировал промпт, отредактированный владельцем в админке, и работал
    # по жёстко зашитому тексту — из админки это было никак не видно.
    # Пустое поле = откат на одноимённый файл `rewriter/prompts/*.txt`
    # (см. `rewriter/client.py::resolve_rewrite_template`).
    rewrite_prompt_template: str = Field(
        default_factory=lambda: _prompt_file_default("default"),
        alias="REWRITE_PROMPT_TEMPLATE",
    )
    rewrite_prompt_news: str = Field(
        default_factory=lambda: _prompt_file_default("news"), alias="REWRITE_PROMPT_NEWS",
    )
    rewrite_prompt_opinion: str = Field(
        default_factory=lambda: _prompt_file_default("opinion"), alias="REWRITE_PROMPT_OPINION",
    )
    rewrite_prompt_instruction: str = Field(
        default_factory=lambda: _prompt_file_default("instruction"),
        alias="REWRITE_PROMPT_INSTRUCTION",
    )
    rewrite_prompt_humor: str = Field(
        default_factory=lambda: _prompt_file_default("humor"), alias="REWRITE_PROMPT_HUMOR",
    )

    # Анти-ИИ блок: приклеивается к ЛЮБОМУ стиль-промпту (см.
    # `rewriter/client.py::build_rewrite_prompt`). Отдельным полем, а не
    # правкой каждого из пяти шаблонов — правило одно на всех.
    rewrite_humanize_enabled: bool = Field(True, alias="REWRITE_HUMANIZE_ENABLED")
    rewrite_humanize_instructions: str = Field(
        _DEFAULT_HUMANIZE_INSTRUCTIONS, alias="REWRITE_HUMANIZE_INSTRUCTIONS",
    )
    # Температура LLM при рерайте. Раньше была зашита как 0.8 прямо в вызове —
    # единственный параметр качества рерайта, недоступный владельцу. Ниже 0.7
    # текст заметно «сушится» и становится шаблоннее, выше 1.0 растёт риск
    # искажения фактов, поэтому диапазон ограничен в settings_store.
    rewrite_temperature: float = Field(0.8, alias="REWRITE_TEMPERATURE")

    # --- F16-доп.: переход по ссылке из поста для «настоящего» рерайта ---
    # Пост часто содержит только короткий тизер + ссылку на полную статью —
    # без перехода по ссылке рерайт неизбежно выглядит как синонимайз одного
    # абзаца, а не пересказ. Если включено — из первой ссылки в посте
    # вытаскивается основной текст (и обложка, если у поста своей нет) через
    # `enrichment/link_content.py`, ошибка/недоступность ссылки не ломает
    # обычный рерайт по одному посту (см. там же).
    fetch_link_content_enabled: bool = Field(True, alias="FETCH_LINK_CONTENT_ENABLED")
    link_content_max_chars: int = Field(6000, alias="LINK_CONTENT_MAX_CHARS")
    link_fetch_timeout_seconds: float = Field(10.0, alias="LINK_FETCH_TIMEOUT_SECONDS")

    # --- F06-доп.: N вариантов рерайта на пост, выбор — в боте/веб-админке ---
    # Каждый вариант — отдельный LLM-вызов (см. scheduler/jobs.py), поэтому
    # токены/стоимость растут линейно с этим числом. 1 = старое поведение
    # (единственный текст, без кнопок переключения вариантов).
    rewrite_variant_count: int = Field(1, alias="REWRITE_VARIANT_COUNT")

    # --- F23: веб-админка (Фаза 5) ---
    # Бутстрап-ключи живут ТОЛЬКО в .env (никогда в БД — иначе шифрование
    # секретов ключом из той же БД не защищало бы ни от чего). Генерируются
    # автоматически при первом запуске setup-визарда, см. tg_repost/crypto.py.
    webui_master_key: str = Field("", alias="WEBUI_MASTER_KEY")
    webui_session_secret: str = Field("", alias="WEBUI_SESSION_SECRET")

    # --- БД ---
    database_url: str = Field("sqlite:///tg_repost.db", alias="DATABASE_URL")

    # --- Фильтрация (F03) ---
    # `NoDecode` обязателен: без него pydantic-settings пытается json.loads()
    # сырое значение из .env ДО того, как отработает `_split_csv` ниже — и
    # падает даже на "" (не говоря о "a,b,c"), т.к. это не валидный JSON.
    # Найдено при первом реальном прогоне через Docker/.env (раньше никогда
    # не проверялось живым .env-файлом, только через os.environ в тестах).
    filter_stop_words: Annotated[list[str], NoDecode] = Field(
        default_factory=list, alias="FILTER_STOP_WORDS"
    )
    filter_required_words: Annotated[list[str], NoDecode] = Field(
        default_factory=list, alias="FILTER_REQUIRED_WORDS"
    )

    # --- Поведение пайплайна ---
    pipeline_interval_seconds: int = Field(30, alias="PIPELINE_INTERVAL_SECONDS")
    auto_post_enabled: bool = Field(False, alias="AUTO_POST_ENABLED")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    # --- F17: антибан-механики ---
    listener_min_delay_seconds: float = Field(0.5, alias="LISTENER_MIN_DELAY_SECONDS")
    listener_max_delay_seconds: float = Field(3.0, alias="LISTENER_MAX_DELAY_SECONDS")
    max_reads_per_hour: int = Field(200, alias="MAX_READS_PER_HOUR")

    # --- F11: авто-постинг по расписанию (слоты) ---
    scheduled_posting_enabled: bool = Field(False, alias="SCHEDULED_POSTING_ENABLED")
    # Временные слоты публикации в формате HH:MM, через запятую. `NoDecode` —
    # см. комментарий у filter_stop_words выше.
    posting_slots: Annotated[list[str], NoDecode] = Field(
        default_factory=list, alias="POSTING_SLOTS"
    )
    # Сколько одобренных постов выпускать за один слот.
    posting_batch_per_slot: int = Field(1, alias="POSTING_BATCH_PER_SLOT")

    # --- F13: семантический дубль-чек (эмбеддинги) ---
    semantic_dedup_enabled: bool = Field(False, alias="SEMANTIC_DEDUP_ENABLED")
    openai_embedding_model: str = Field(
        "text-embedding-3-small", alias="OPENAI_EMBEDDING_MODEL"
    )
    semantic_similarity_threshold: float = Field(
        0.92, alias="SEMANTIC_SIMILARITY_THRESHOLD"
    )
    dedup_window_days: int = Field(3, alias="DEDUP_WINDOW_DAYS")

    # --- F14: статистика ---
    stats_enabled: bool = Field(False, alias="STATS_ENABLED")
    stats_interval_minutes: int = Field(60, alias="STATS_INTERVAL_MINUTES")
    stats_window_days: int = Field(7, alias="STATS_WINDOW_DAYS")

    # --- F25: авто-реакция на негативные реакции ---
    # 0 — выключено (порог не может быть достигнут отрицательным/нулевым числом реакций).
    negative_reaction_threshold: int = Field(0, alias="NEGATIVE_REACTION_THRESHOLD")
    auto_delete_on_negative: bool = Field(False, alias="AUTO_DELETE_ON_NEGATIVE")
    # Потолок автоматических удалений в час — защита от скоординированного
    # всплеска негативных реакций (бригадинг), который иначе мог бы вызвать
    # массовое необратимое удаление легитимных постов за один цикл сбора
    # статистики (найдено при security-аудите Фазы 5+). При достижении
    # потолка пост всё равно уведомляется владельцу, просто НЕ удаляется
    # автоматически — решение остаётся за человеком.
    max_auto_deletes_per_hour: int = Field(5, alias="MAX_AUTO_DELETES_PER_HOUR")

    # --- F15: стиль-профили рерайта ---
    # Профиль по умолчанию, если у источника не задан свой (имя файла промпта).
    default_style_profile: str = Field("default", alias="DEFAULT_STYLE_PROFILE")

    # --- F16: поиск дополнительных источников (Brave Search) ---
    enable_source_enrichment: bool = Field(False, alias="ENABLE_SOURCE_ENRICHMENT")
    brave_api_key: str = Field("", alias="BRAVE_API_KEY")
    brave_search_url: str = Field(
        "https://api.search.brave.com/res/v1/web/search", alias="BRAVE_SEARCH_URL"
    )
    # Сколько результатов запрашивать у Brave и сколько максимум вставлять в пост.
    enrichment_max_results: int = Field(8, alias="ENRICHMENT_MAX_RESULTS")
    enrichment_max_sources: int = Field(3, alias="ENRICHMENT_MAX_SOURCES")

    # --- F24: сравнение версий источников (доп. LLM-вызов, поэтому опционально) ---
    version_comparison_enabled: bool = Field(False, alias="VERSION_COMPARISON_ENABLED")

    # --- F18: авто-обложки ---
    enable_auto_cover: bool = Field(False, alias="ENABLE_AUTO_COVER")
    cover_strategy: str = Field("unsplash", alias="COVER_STRATEGY")  # unsplash | comfyui | openai
    # "openai" — генерация через УЖЕ настроенный OpenAI-совместимый провайдер
    # рерайта (openai_base_url/openai_api_key, см. группу "rewrite") — свой
    # ключ здесь не нужен, только своя модель (картиночная, не чат) и свой
    # промпт. Работает с любым провайдером, отдающим data[].b64_json из
    # images.generate() — так же, как реальный OpenAI DALL-E.
    cover_openai_model: str = Field(
        "black-forest-labs/flux.2-klein-4b", alias="COVER_OPENAI_MODEL"
    )
    cover_image_prompt_template: str = Field(
        _DEFAULT_COVER_IMAGE_PROMPT, alias="COVER_IMAGE_PROMPT_TEMPLATE"
    )
    # Размер картинки у стратегии "openai". Раньше был зашит как 1024x1024 —
    # квадрат, хотя обложка поста в Telegram показывается широкой: квадрат
    # обрезается по краям, и как раз композиционно важное уезжает из кадра.
    cover_openai_image_size: str = Field("1792x1024", alias="COVER_OPENAI_IMAGE_SIZE")
    # Промпт для ТЕКСТОВОЙ модели, подбирающей короткий запрос к Unsplash/
    # ComfyUI. Раньше лежал только в файле cover_prompt.txt и не редактировался
    # из админки, хотя именно он определяет, что за картинка приедет.
    # Пусто = откат на файл `rewriter/prompts/cover_prompt.txt`.
    cover_search_prompt_template: str = Field(
        _DEFAULT_COVER_SEARCH_PROMPT, alias="COVER_SEARCH_PROMPT_TEMPLATE"
    )
    # F18-доп.: N вариантов обложки на пост (отдельно от rewrite_variant_count
    # выше — можно, например, хотеть 3 текста и 1 обложку). Каждый вариант —
    # отдельный вызов генератора (см. scheduler/jobs.py). 1 = старое поведение.
    cover_variant_count: int = Field(1, alias="COVER_VARIANT_COUNT")
    unsplash_access_key: str = Field("", alias="UNSPLASH_ACCESS_KEY")
    unsplash_api_url: str = Field(
        "https://api.unsplash.com/photos/random", alias="UNSPLASH_API_URL"
    )
    comfyui_base_url: str = Field("http://127.0.0.1:8188", alias="COMFYUI_BASE_URL")
    # Путь к workflow в API-формате (экспорт из ComfyUI), специфичен для установки
    # пользователя (чекпойнт, сэмплер) — общего шаблона на все случаи нет.
    comfyui_workflow_path: str = Field("", alias="COMFYUI_WORKFLOW_PATH")
    # ID узла (ключ в JSON workflow) CLIPTextEncode, куда подставляется промпт.
    comfyui_positive_node_id: str = Field("", alias="COMFYUI_POSITIVE_NODE_ID")
    # ID узла негативного CLIPTextEncode. Пусто — негатив из workflow не
    # трогается. Заполнить важно именно для обложек: без явного запрета
    # модели упорно дорисовывают на «новостных» картинках надписи, подписи и
    # псевдологотипы, а одного «no text» в позитивном промпте не хватает.
    comfyui_negative_node_id: str = Field("", alias="COMFYUI_NEGATIVE_NODE_ID")
    comfyui_negative_prompt: str = Field(
        "text, words, letters, numbers, caption, subtitle, watermark, signature, "
        "logo, brand, poster, banner, sign, label, ui, interface, infographic, "
        "chart, diagram, blurry, low quality, deformed",
        alias="COMFYUI_NEGATIVE_PROMPT",
    )
    comfyui_poll_attempts: int = Field(60, alias="COMFYUI_POLL_ATTEMPTS")
    comfyui_poll_interval_seconds: float = Field(2.0, alias="COMFYUI_POLL_INTERVAL_SECONDS")

    # --- F19: умное расписание ---
    smart_schedule_min_posts: int = Field(20, alias="SMART_SCHEDULE_MIN_POSTS")
    smart_schedule_top_n: int = Field(3, alias="SMART_SCHEDULE_TOP_N")
    smart_schedule_window_days: int = Field(21, alias="SMART_SCHEDULE_WINDOW_DAYS")
    # По умолчанию выключено — рекомендация видна на /best_times и
    # /stats/best-times, применяется вручную кнопкой «Применить сейчас» или
    # (если явно включено) периодической джобой раз в сутки, см.
    # scheduler/smart_schedule.py::auto_apply_slots_job (аудит Фазы 5+).
    smart_schedule_auto_apply: bool = Field(False, alias="SMART_SCHEDULE_AUTO_APPLY")

    # --- F20: авто-дайджест ---
    digest_enabled: bool = Field(False, alias="DIGEST_ENABLED")
    # День недели для APScheduler CronTrigger: mon,tue,wed,thu,fri,sat,sun.
    digest_day_of_week: str = Field("sun", alias="DIGEST_DAY_OF_WEEK")
    digest_hour: int = Field(12, alias="DIGEST_HOUR")
    digest_minute: int = Field(0, alias="DIGEST_MINUTE")
    digest_top_n: int = Field(5, alias="DIGEST_TOP_N")
    digest_window_days: int = Field(7, alias="DIGEST_WINDOW_DAYS")

    # --- F21: нативная реклама ---
    # Каждый N-й опубликованный обычный пост — рекламный. 0 = выключено.
    ad_every_nth_post: int = Field(0, alias="AD_EVERY_NTH_POST")

    # --- F22: growth-трекер (каркас — сбор данных + простой отчёт) ---
    growth_tracking_enabled: bool = Field(False, alias="GROWTH_TRACKING_ENABLED")
    growth_snapshot_interval_minutes: int = Field(360, alias="GROWTH_SNAPSHOT_INTERVAL_MINUTES")
    growth_min_snapshots: int = Field(2, alias="GROWTH_MIN_SNAPSHOTS")
    growth_report_window_days: int = Field(7, alias="GROWTH_REPORT_WINDOW_DAYS")

    # --- F34: inline-кнопка "источник" на опубликованном посте ---
    # Только для постов с `source_link` (kind=SOURCE) — AD/DIGEST/POLL его
    # не имеют, кнопка на них не появляется независимо от этой настройки.
    post_source_button_enabled: bool = Field(False, alias="POST_SOURCE_BUTTON_ENABLED")
    post_source_button_label: str = Field("Читать в источнике", alias="POST_SOURCE_BUTTON_LABEL")

    @field_validator("filter_stop_words", "filter_required_words", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> list[str]:
        """Разбить строку из .env вида "a, b, c" в список нормализованных слов."""
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [w.strip().lower() for w in value.split(",") if w.strip()]
        if isinstance(value, list):
            return [str(w).strip().lower() for w in value if str(w).strip()]
        return []

    @field_validator("posting_slots", mode="before")
    @classmethod
    def _split_slots(cls, value: object) -> list[str]:
        """Разбить слоты "10:00, 14:00" в список без приведения регистра."""
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [s.strip() for s in value.split(",") if s.strip()]
        if isinstance(value, list):
            return [str(s).strip() for s in value if str(s).strip()]
        return []

    @field_validator("tg_api_id", "tg_owner_user_id", "mtproto_proxy_port", mode="before")
    @classmethod
    def _blank_int_to_zero(cls, value: object) -> object:
        """Пустая строка (`TG_API_ID=` — обычный плейсхолдер из .env.example,
        пока секрет не задан через `/setup`) не должна валить `Settings()`:
        pydantic иначе пытается распарсить "" как int и падает с
        ValidationError вместо мягкого дефолта 0 (`is_minimally_configured`
        корректно интерпретирует 0 как «не настроено»; для mtproto_proxy_port
        0 так же означает «прокси не настроен», см. listener.py::_mtproxy_kwargs
        — проверяет host, но port должен хотя бы парситься)."""
        if value == "":
            return 0
        return value

    @property
    def media_dir(self) -> str:
        """Каталог для скачанных медиа источников."""
        return "media"

    @property
    def is_minimally_configured(self) -> bool:
        """Достаточно ли секретов, чтобы поднять Telethon-listener и бота.

        Веб-сервер (Фаза 5) стартует независимо от этого — см. `main.py`.
        Пока False, listener/бот/планировщик не запускаются, и пользователь
        видит в логе подсказку открыть `/setup`.
        """
        return bool(
            self.tg_api_id
            and self.tg_api_hash
            and self.tg_bot_token
            and self.tg_owner_user_id
            and self.openai_api_key
        )


# Поля, которые веб-админка (Фаза 5) считает секретами: хранятся в таблице
# `secrets` зашифрованными (см. tg_repost/crypto.py), редактируются write-only,
# никогда не показываются в открытом виде. Имена — реальные snake_case
# атрибуты `Settings`, а не ALIAS (`.env`-имена) — так совпадает с ключом,
# который пишет/читает `webui/settings_store.py`. ИСКЛЮЧЕНИЕ: "guardian_bot_token"
# НЕ атрибут `Settings` (это токен ДРУГОГО бота, отдельный процесс) — хранится
# здесь же (одна инфраструктура шифрования на оба процесса, `WEBUI_MASTER_KEY`
# общий), но `_apply_secret_overrides` ниже пропускает его через `Settings`
# (hasattr=False) — расшифровывает и применяет его САМ `guardian/config.py`
# (кросс-процессное чтение таблицы `secrets`, см. его docstring).
SECRET_FIELD_NAMES: tuple[str, ...] = (
    "tg_api_hash",
    "tg_session_string",
    "tg_bot_token",
    "openai_api_key",
    "brave_api_key",
    "unsplash_access_key",
    "mtproto_proxy_secret",
    "telethon_proxy_url",
    "bot_api_proxy_url",
    "guardian_bot_token",
)


def _coerce_db_value(raw_value: str, value_type: str) -> object:
    """Распарсить JSON-значение из `app_settings.value` по `value_type`."""
    data = json.loads(raw_value)
    if value_type == "int":
        return int(data)
    if value_type == "float":
        return float(data)
    if value_type == "bool":
        return bool(data)
    if value_type == "csv_list":
        return list(data)
    return str(data)


def _apply_db_overrides(settings: Settings) -> None:
    """Оверлей значений из `app_settings` (веб-админка) поверх .env-дефолтов.

    Ленивые импорты `db.models`/`db.session` — чтобы у `db/session.py` не
    появилось обратной зависимости от `config.py` (см. комментарий там).
    Любая ошибка (например, таблицы ещё нет — миграция не накатана) не
    должна ронять процесс: работаем на чистых .env-дефолтах.
    """
    try:
        from tg_repost.db.models import AppSetting
        from tg_repost.db.session import session_scope

        with session_scope() as session:
            rows = [(r.key, r.value, r.value_type) for r in session.query(AppSetting).all()]
    except Exception as exc:  # noqa: BLE001
        logger.debug("Оверлей настроек из БД недоступен (%s) — использую .env", exc)
        return

    for key, raw_value, value_type in rows:
        if not hasattr(settings, key):
            continue
        try:
            setattr(settings, key, _coerce_db_value(raw_value, value_type))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("Настройка '%s' из БД повреждена, пропущена: %s", key, exc)


def _apply_secret_overrides(settings: Settings) -> None:
    """Оверлей расшифрованных секретов из таблицы `secrets` поверх .env.

    До первого запуска setup-визарда `webui_master_key` пуст — секретов в БД
    ещё не существует, оверлей становится no-op.
    """
    if not settings.webui_master_key:
        return
    try:
        from tg_repost.crypto import InvalidToken, decrypt
        from tg_repost.db.models import Secret
        from tg_repost.db.session import session_scope

        with session_scope() as session:
            rows = [(r.key, r.encrypted_value) for r in session.query(Secret).all()]
    except Exception as exc:  # noqa: BLE001
        logger.debug("Оверлей секретов из БД недоступен (%s) — использую .env", exc)
        return

    for key, encrypted_value in rows:
        if key not in SECRET_FIELD_NAMES or not hasattr(settings, key):
            continue
        try:
            setattr(settings, key, decrypt(encrypted_value, settings.webui_master_key))
        except InvalidToken:
            logger.error(
                "Секрет '%s' не расшифрован — неверный WEBUI_MASTER_KEY?", key
            )


@lru_cache
def get_settings() -> Settings:
    """Настройки: .env-дефолты + оверлей из БД (веб-админка, Фаза 5).

    Кэшируется на процесс; после изменения настройки/секрета через веб-админку
    вызывающий код обязан вызвать `invalidate_settings_cache()`, иначе кэш
    переживёт сохранение до следующего перезапуска.
    """
    settings = Settings()  # type: ignore[call-arg]
    _apply_db_overrides(settings)
    _apply_secret_overrides(settings)
    return settings


def invalidate_settings_cache() -> None:
    """Сбросить кэш `get_settings()` — вызывается после сохранения настройки/
    секрета через веб-админку, чтобы изменение применилось без перезапуска
    процесса (для значений из категории "live", см. план Фазы 5)."""
    get_settings.cache_clear()
