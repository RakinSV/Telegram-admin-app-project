"""Конфигурация Engage — бота вовлечения участников (F42–F47).

Третий процесс системы. Разделение с остальными двумя — по СОБЕСЕДНИКУ, а не
по фичам:
  • репост-бот  → говорит с ВЛАДЕЛЬЦЕМ (кнопки одобрения постов);
  • Guardian    → работает В ГРУППЕ (капча, антиспам, варны);
  • Engage      → говорит с УЧАСТНИКАМИ (квизы, конкурсы, рефералы, предложка).

Почему отдельный бот, а не хендлеры в репост-боте: deep-link рефералки ведёт
именно на него, участники пишут ему в личку, и смешивать «бот владельца» с
«ботом подписчиков» — плохой UX (подписчик видит чужие админ-кнопки) и лишняя
поверхность атаки.

**БД — общая с tg_repost, а не своя** (в отличие от Guardian). Причина в связях:
квиз делается ИЗ поста (`Post`), реферальная ссылка — это `InviteLink`, а
приведённые ею участники учитываются в `MemberOrigin` (F41). Своя БД означала
бы кросс-базовые джойны на каждый чих. Guardian отделён оправданно — его
состояние модерации ни с чем из контента не связано.
"""

from __future__ import annotations

import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)


class EngageSettings(BaseSettings):
    """Настройки Engage. Читает тот же `.env`, что и остальные два процесса
    (общий docker-compose), `extra="ignore"` не даёт чужим полям мешать."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore",
    )

    # Токен ОТДЕЛЬНОГО бота (@BotFather → /newbot). Как и у Guardian, задаётся
    # в веб-админке (шифрованная таблица `secrets`), а не правкой .env на
    # сервере — см. `_secret_override` ниже.
    engage_bot_token: str = Field("", alias="ENGAGE_BOT_TOKEN")

    @property
    def is_configured(self) -> bool:
        return bool(self.engage_bot_token)


def _secret_override() -> dict[str, object]:
    """Оверлей `engage_bot_token` из ЗАШИФРОВАННОЙ таблицы `secrets`.

    Тот же приём, что в `guardian/config.py::_secret_override` (см. его
    подробный комментарий): `WEBUI_MASTER_KEY` читается СВЕЖО из `.env` на
    каждый вызов, иначе пришлось бы рестартовать процессы в строго
    определённом порядке только ради того, чтобы этот увидел уже
    сгенерированный ключ.
    """
    from dotenv import load_dotenv

    load_dotenv()
    master_key = os.environ.get("WEBUI_MASTER_KEY", "")
    if not master_key:
        return {}
    try:
        from tg_repost.crypto import InvalidToken, decrypt
        from tg_repost.db.models import Secret
        from tg_repost.db.session import session_scope

        with session_scope() as session:
            row = (
                session.query(Secret)
                .filter(Secret.key == "engage_bot_token")
                .one_or_none()
            )
    except Exception:  # noqa: BLE001
        # БД может быть ещё не мигрирована (первый запуск) — это не повод
        # ронять процесс: без токена он всё равно корректно не стартует.
        return {}
    if row is None:
        return {}
    try:
        return {"engage_bot_token": decrypt(row.encrypted_value, master_key)}
    except InvalidToken:
        logger.warning(
            "Токен Engage не расшифровывается текущим WEBUI_MASTER_KEY — "
            "ключ сменили после сохранения секрета?",
        )
        return {}


def get_engage_settings() -> EngageSettings:
    """Настройки со свежим оверлеем секрета.

    Не кэшируется (в отличие от `tg_repost.config.get_settings`): Engage —
    ОТДЕЛЬНЫЙ ОС-процесс, и явная инвалидация кэша из веб-панели до него не
    достучится. Чтение одной строки SQLite дешевле, чем объяснять владельцу,
    почему сохранённый токен «не применился».
    """
    settings = EngageSettings()  # type: ignore[call-arg]
    override = _secret_override()
    if override:
        return settings.model_copy(update=override)
    return settings
