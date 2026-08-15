"""CRM участников (F63) — веб-роуты: карточки, теги, сегменты.

Список людей строится ИЗ СЕГМЕНТА, а не отдельным набором фильтров в форме.
Так владелец видит ровно тех, кому уйдёт рассылка (F64): один и тот же
механизм отбора и на странице, и при отправке. Две независимые реализации
«кого отобрать» разошлись бы, и разница обнаружилась бы на живой аудитории.

Предпросмотр числа людей обязателен перед сохранением сегмента: цифра «1»
против «8420» — единственное, что отличает узкую выборку от всей базы, и
увидеть её надо ДО того, как сегментом воспользуется рассылка.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from tg_repost import contacts_repo, segments_repo
from tg_repost.webui import audit, i18n
from tg_repost.webui.templating import build_templates
from tg_repost.webui.auth import require_login

_BASE_DIR = Path(__file__).parent
_templates = build_templates()

# Сколько карточек показываем разом. Страница — обзор, а не выгрузка: для
# выгрузки есть /export, а список на несколько тысяч строк не читается.
_LIST_LIMIT = 200


def build_contacts_router() -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_login)])

    @router.get("/contacts", response_class=HTMLResponse)
    async def contacts_page(request: Request, tag: str = "") -> Response:
        selected = contacts_repo.normalize_tag(tag) if tag else ""
        if selected:
            user_ids = contacts_repo.users_with_tag(selected)
        else:
            # Без фильтра показываем тех, о ком вообще есть что показать —
            # людей с тегами. Показывать «всех известных» здесь бессмысленно:
            # у большинства в карточке будет пусто.
            user_ids = sorted({
                user_id
                for known_tag, _count in contacts_repo.all_tags()
                for user_id in contacts_repo.users_with_tag(known_tag)
            })

        cards = [contacts_repo.build_card(uid) for uid in user_ids[:_LIST_LIMIT]]
        return _templates.TemplateResponse(
            request, "contacts.html",
            {
                "cards": cards,
                "tags": contacts_repo.all_tags(),
                "selected_tag": selected,
                "total": len(user_ids),
                "shown": len(cards),
                "limit": _LIST_LIMIT,
            },
        )

    @router.get("/contacts/{user_id}", response_class=HTMLResponse)
    async def contact_detail(request: Request, user_id: int) -> Response:
        return _templates.TemplateResponse(
            request, "contact_detail.html",
            {"card": contacts_repo.build_card(user_id)},
        )

    @router.post("/contacts/{user_id}/tags")
    async def contact_add_tag(user_id: int, tag: str = Form("")) -> Response:
        if contacts_repo.add_tag(user_id, tag):
            audit.record_audit("contact_tag_add", target=f"id{user_id}", detail=tag)
        return RedirectResponse(url=f"/contacts/{user_id}", status_code=303)

    @router.post("/contacts/{user_id}/tags/delete")
    async def contact_remove_tag(user_id: int, tag: str = Form("")) -> Response:
        if contacts_repo.remove_tag(user_id, tag):
            audit.record_audit("contact_tag_remove", target=f"id{user_id}", detail=tag)
        return RedirectResponse(url=f"/contacts/{user_id}", status_code=303)

    @router.post("/contacts/{user_id}/note")
    async def contact_set_note(user_id: int, note: str = Form("")) -> Response:
        contacts_repo.set_note(user_id, note)
        audit.record_audit(
            "contact_note", target=f"id{user_id}",
            detail="очищена" if not note.strip() else f"{len(note.strip())} симв.",
        )
        return RedirectResponse(url=f"/contacts/{user_id}", status_code=303)

    @router.get("/segments", response_class=HTMLResponse)
    async def segments_page(request: Request, error: str = "") -> Response:
        return _templates.TemplateResponse(
            request, "segments.html", _segments_context(error or None),
        )

    @router.post("/segments")
    async def segment_save(
        request: Request,
        name: str = Form(""),
        tag: str = Form(""),
        min_points: str = Form(""),
        origin: str = Form(""),
        active_only: str = Form(""),
        everyone: str = Form(""),
    ) -> Response:
        filter_dict: dict = {}
        if everyone:
            filter_dict["everyone"] = True
        else:
            if tag.strip():
                filter_dict["tag"] = tag.strip()
            if min_points.strip():
                try:
                    filter_dict["min_points"] = int(min_points)
                except ValueError:
                    return _segments_error(request, i18n.t("segments.error_points_number"))
            if origin.strip():
                filter_dict["origin"] = origin.strip()
            if active_only:
                filter_dict["active_only"] = True

        try:
            segment_id = segments_repo.save(name, filter_dict)
        except segments_repo.InvalidFilter as exc:
            # Показываем ТЕКСТ ошибки как есть: он объясняет, почему фильтр
            # опасен («пустой совпал бы со всей базой»), а обобщённое
            # «неверные данные» это объяснение потеряло бы.
            return _segments_error(request, str(exc))

        audit.record_audit(
            "segment_save", target=name.strip(), detail=str(filter_dict),
        )
        return RedirectResponse(url=f"/segments?saved={segment_id}", status_code=303)

    @router.post("/segments/{segment_id}/delete")
    async def segment_delete(segment_id: int) -> Response:
        view = segments_repo.get(segment_id)
        if segments_repo.delete(segment_id) and view is not None:
            audit.record_audit("segment_delete", target=view.name)
        return RedirectResponse(url="/segments", status_code=303)

    def _segments_error(request: Request, message: str) -> Response:
        return _templates.TemplateResponse(
            request, "segments.html", _segments_context(message), status_code=400,
        )

    return router


def _segments_context(error: str | None = None) -> dict:
    rows = []
    for view in segments_repo.list_all():
        # Число людей считается СЕЙЧАС, а не берётся из сохранённого поля:
        # сегмент — это запрос, и его состав меняется сам по себе, когда
        # человек получает тег или покидает чат.
        rows.append({"segment": view, "size": len(segments_repo.evaluate(view.filter))})
    return {
        "segments": rows,
        "tags": contacts_repo.all_tags(),
        "error": error,
        "known_keys": sorted(segments_repo.KNOWN_KEYS),
    }
