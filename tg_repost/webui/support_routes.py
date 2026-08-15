"""Инбокс поддержки (F68) — веб-роуты.

КАРТОЧКА ЧЕЛОВЕКА ПОКАЗЫВАЕТСЯ РЯДОМ С ПЕРЕПИСКОЙ. Оператор, отвечающий на
вопрос, должен видеть, откуда человек пришёл, сколько привёл друзей и не
забанен ли он в группе. Без этого поддержка отвечает незнакомцу и разговор
получается формальным там, где мог быть человеческим.

ОТПРАВКА ИДЁТ ЧЕРЕЗ БОТА ENGAGE — того самого, которому человек написал.
Отвечать другим ботом нельзя: для человека это будет сообщение от
неизвестного адресата, и половина решит, что это спам.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from tg_repost import contacts_repo, support_repo
from tg_repost.logging_conf import get_logger
from tg_repost.webui import audit, i18n
from tg_repost.webui.auth import require_login

logger = get_logger(__name__)

_BASE_DIR = Path(__file__).parent
_templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))
_templates.env.globals["t"] = i18n.t
_templates.env.globals["current_lang"] = i18n.get_current_lang


async def _send_reply(user_id: int, text: str) -> bool:
    """Отправить ответ через бота Engage. `False` — не получилось.

    Сбой отправки НЕ отменяет запись в переписке: оператор потратил время на
    ответ, и потерять его текст из-за сетевой ошибки хуже, чем показать
    предупреждение и дать отправить снова.
    """
    try:
        from engage.bot import build_reply_bot

        bot = build_reply_bot()
        if bot is None:
            logger.warning("F68: ENGAGE_BOT_TOKEN не настроен — ответ не отправлен")
            return False
        try:
            await bot.send_message(user_id, text)
        finally:
            # Сессию закрываем всегда: экземпляр разовый, и оставленное
            # соединение утекало бы на каждый ответ оператора.
            await bot.session.close()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("F68: не удалось отправить ответ %s: %s", user_id, exc)
        return False


def build_support_router() -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_login)])

    @router.get("/support", response_class=HTMLResponse)
    async def support_inbox(request: Request, status: str = "") -> Response:
        selected = status if status in ("open", "closed") else None
        return _templates.TemplateResponse(
            request, "support.html",
            {
                "threads": support_repo.list_threads(selected),
                "selected_status": selected,
                "unread": support_repo.unread_count(),
            },
        )

    @router.get("/support/{thread_id}", response_class=HTMLResponse)
    async def support_thread(
        request: Request, thread_id: int, error: str = "",
    ) -> Response:
        thread = support_repo.get_thread(thread_id)
        if thread is None:
            return RedirectResponse(url="/support", status_code=303)

        support_repo.mark_read(thread_id)
        return _templates.TemplateResponse(
            request, "support_thread.html",
            {
                "thread": thread,
                "messages": support_repo.messages_of(thread_id),
                # Карточка рядом с перепиской — см. docstring модуля.
                "card": contacts_repo.build_card(thread.user_id),
                "error": error or None,
            },
        )

    @router.post("/support/{thread_id}/reply")
    async def support_reply(
        request: Request, thread_id: int, text: str = Form(""),
    ) -> Response:
        thread = support_repo.get_thread(thread_id)
        if thread is None or not text.strip():
            return RedirectResponse(url=f"/support/{thread_id}", status_code=303)

        author = str(request.session.get("role") or "owner")
        sent = await _send_reply(thread.user_id, text)
        # Записываем в любом случае: текст оператора не должен пропасть
        # из-за сетевой ошибки.
        support_repo.record_reply(thread_id, text, author=author)
        audit.record_audit(
            "support_reply", target=f"id{thread.user_id}",
            detail="отправлено" if sent else "НЕ доставлено",
        )
        if not sent:
            return RedirectResponse(
                url=f"/support/{thread_id}?error={i18n.t('support.error_not_sent')}",
                status_code=303,
            )
        return RedirectResponse(url=f"/support/{thread_id}", status_code=303)

    @router.post("/support/{thread_id}/close")
    async def support_close(thread_id: int) -> Response:
        support_repo.set_status(thread_id, support_repo.STATUS_CLOSED)
        return RedirectResponse(url="/support", status_code=303)

    @router.post("/support/{thread_id}/reopen")
    async def support_reopen(thread_id: int) -> Response:
        support_repo.set_status(thread_id, support_repo.STATUS_OPEN)
        return RedirectResponse(url=f"/support/{thread_id}", status_code=303)

    return router
