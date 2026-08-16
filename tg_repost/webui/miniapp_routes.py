"""Mini App: витрина внутри Telegram (F74) — веб-роуты.

⚠️ ЭТО ПЕРВАЯ ПУБЛИЧНО ДОСТУПНАЯ ПОВЕРХНОСТЬ СИСТЕМЫ. Вся остальная админка
живёт за логином и наружу не торчит вовсе — это записанный трейдофф модели
угроз. Мини-апп иначе не работает: Telegram открывает его во встроенном
браузере по HTTPS-адресу, и адрес обязан быть доступен извне.

ЧЕМ ЭТО ОТЛИЧАЕТСЯ ОТ «ПРОСТО ОТКРЫТЬ АДМИНКУ НАРУЖУ»:

* аутентификация — ПОДПИСЬ TELEGRAM (`initData`), а не пароль и не ключ.
  Подделать её нельзя, не зная токена бота, а токен наружу не выходит;
* видно ТОЛЬКО СВОЁ. Каждый запрос обслуживает данные того человека, чей
  идентификатор пришёл в подписанных данных, и никакого способа спросить
  «покажи чужое» в интерфейсе нет;
* сюда не выведен НИ ОДИН админский экран. Витрина — это лидерборд, свои
  рефералы, каталог и своя подписка.

ПОДПИСЬ ПРОВЕРЯЕТСЯ НА КАЖДЫЙ ЗАПРОС, а не один раз при входе. Сессии здесь
нет намеренно: сессия — это состояние, которое живёт дольше подписи и
переживает её протухание, то есть ровно та лазейка, которую срок годности
подписи и закрывает.

ТЕЛО ОТВЕТА НЕ ОБЪЯСНЯЕТ, ЧТО ИМЕННО НЕ ТАК с подписью: подробность вида
«верна, но истекла» помогает подбирать.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse

from tg_repost.logging_conf import get_logger
from tg_repost.miniapp import auth
from tg_repost.webui.templating import build_templates

logger = get_logger(__name__)
_templates = build_templates()


def _authenticate(init_data: str) -> auth.WebAppUser | None:
    token = auth.engage_bot_token()
    if not token:
        logger.warning("F74: ENGAGE_BOT_TOKEN не задан — мини-апп не работает")
        return None
    try:
        return auth.parse_init_data(init_data, token)
    except auth.InvalidInitData as exc:
        # Причина — только в лог, наружу общий отказ.
        logger.info("F74: отклонены данные мини-аппа: %s", exc)
        return None


def build_miniapp_router() -> APIRouter:
    """Роутер БЕЗ `require_login`: у мини-аппа своя аутентификация."""
    router = APIRouter()

    @router.get("/app", response_class=HTMLResponse)
    async def app_shell(request: Request) -> Response:
        """Оболочка. Данные не отдаёт — их запрашивает страница ниже.

        Разделение нужно потому, что `initData` доступна только JavaScript'у
        внутри Telegram: в первом GET её ещё нет, и наполнить страницу
        сервер не может физически.
        """
        return _templates.TemplateResponse(request, "miniapp.html", {})

    @router.post("/app/data", response_class=HTMLResponse)
    async def app_data(request: Request, init_data: str = Form("")) -> Response:
        user = _authenticate(init_data)
        if user is None:
            return _templates.TemplateResponse(
                request, "miniapp_denied.html", {}, status_code=403,
            )

        from tg_repost import (
            affiliate_repo,
            quiz_repo,
            referrals_repo,
            shop_repo,
            subscriptions_repo,
            targets_repo,
        )
        from tg_repost.config import get_settings

        settings = get_settings()

        # Лидерборд считается ПО ЧАТУ, поэтому нужен конкретный: берём первую
        # активную цель — ту же, что и реферальные ссылки в `engage/start`.
        # Целей нет — таблицы просто не будет, а не пустая с нулями.
        active = [t for t in targets_repo.list_targets() if t.is_active]
        chat_id = active[0].chat_id if active else None

        # Лидерборд — единственное место, где видно других людей, и это
        # осознанно: таблица лидеров без соперников бессмысленна. Показаны
        # имя и очки, то есть ровно то, что человек и так видит в общем чате.
        leaders = quiz_repo.leaderboard(chat_id, limit=10) if chat_id else []
        referrals = referrals_repo.stats_for(user.id)

        products = (
            [p for p in shop_repo.list_products(only_active=True) if p.in_stock]
            if settings.shop_enabled else []
        )

        subscription = (
            subscriptions_repo.get(settings.paid_access_chat_id, user.id)
            if settings.paid_access_chat_id else None
        )

        return _templates.TemplateResponse(
            request, "miniapp_data.html",
            {
                "user": user,
                "leaders": leaders,
                "referrals": referrals,
                "products": products,
                "subscription": subscription,
                "balance": affiliate_repo.balance_of(user.id),
            },
        )

    return router
