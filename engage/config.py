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

    # F70: токен платёжного провайдера из @BotFather (/mybots → Payments).
    # Нужен ТОЛЬКО для физических товаров магазина: подписка идёт за Stars,
    # где провайдер не участвует вовсе.
    shop_provider_token: str = Field("", alias="SHOP_PROVIDER_TOKEN")

    @property
    def is_configured(self) -> bool:
        return bool(self.engage_bot_token)

    @property
    def can_accept_fiat(self) -> bool:
        return bool(self.shop_provider_token)


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

        wanted = ("engage_bot_token", "shop_provider_token")
        with session_scope() as session:
            rows = (
                session.query(Secret)
                .filter(Secret.key.in_(wanted))
                .all()
            )
            encrypted = {row.key: row.encrypted_value for row in rows}
    except Exception:  # noqa: BLE001
        # БД может быть ещё не мигрирована (первый запуск) — это не повод
        # ронять процесс: без токена он всё равно корректно не стартует.
        return {}

    result: dict[str, object] = {}
    for key, value in encrypted.items():
        try:
            result[key] = decrypt(value, master_key)
        except InvalidToken:
            logger.warning(
                "Секрет «%s» не расшифровывается текущим WEBUI_MASTER_KEY — "
                "ключ сменили после сохранения?", key,
            )
    return result


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
