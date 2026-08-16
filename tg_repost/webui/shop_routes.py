"""Магазин: товары и заказы (F69) — веб-роуты.

ЦЕНА ВВОДИТСЯ В РУБЛЯХ, ХРАНИТСЯ В КОПЕЙКАХ. Заставлять владельца считать
копейки — верный способ однажды получить товар за 1499 копеек вместо 1499
рублей; перевод делается здесь, в одном месте, а не размазан по формам.

ЗАКАЗЫ — ТОЛЬКО ВЛАДЕЛЬЦУ: в них адреса и телефоны покупателей. Каталог
редактирует он же: цена — это деньги, а не контент.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from tg_repost import shop_repo as shop
from tg_repost.webui import audit, i18n
from tg_repost.webui.auth import require_login
from tg_repost.webui.templating import build_templates

_templates = build_templates()


def rubles_to_minor(raw: str) -> int | None:
    """«1499» или «1499.90» → копейки. `None` — не число.

    Точка и запятая равноправны: владелец наберёт то, что привычно, а
    отказ из-за разделителя выглядит придиркой.
    """
    text = raw.strip().replace(",", ".").replace(" ", "")
    if not text:
        return None
    try:
        value = round(float(text) * 100)
    except ValueError:
        return None
    return value if value > 0 else None


def build_shop_router() -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_login)])

    def _context(error: str | None = None) -> dict:
        from tg_repost.config import get_settings

        settings = get_settings()
        return {
            "products": shop.list_products(),
            "orders": shop.list_orders(),
            "revenue": shop.revenue(settings.shop_currency) / 100,
            "currency": settings.shop_currency,
            "enabled": settings.shop_enabled,
            "error": error,
        }

    @router.get("/shop", response_class=HTMLResponse)
    async def shop_page(request: Request, error: str = "") -> Response:
        return _templates.TemplateResponse(
            request, "shop.html", _context(error or None),
        )

    @router.post("/shop/products")
    async def product_save(
        request: Request,
        product_id: str = Form(""),
        name: str = Form(""),
        price: str = Form(""),
        description: str = Form(""),
        stock: str = Form(""),
    ) -> Response:
        from tg_repost.config import get_settings

        minor = rubles_to_minor(price)
        if minor is None:
            return _templates.TemplateResponse(
                request, "shop.html",
                _context(i18n.t("shop.error_price")), status_code=400,
            )
        try:
            saved = shop.save_product(
                product_id=int(product_id) if product_id.isdigit() else None,
                name=name,
                price=minor,
                description=description,
                currency=get_settings().shop_currency,
                stock=int(stock) if stock.strip().isdigit() else None,
            )
        except shop.InvalidProduct as exc:
            return _templates.TemplateResponse(
                request, "shop.html", _context(str(exc)), status_code=400,
            )
        audit.record_audit("product_save", target=name.strip(), detail=price)
        del saved
        return RedirectResponse(url="/shop", status_code=303)

    @router.post("/shop/products/{product_id}/toggle")
    async def product_toggle(request: Request, product_id: int) -> Response:
        view = shop.get_product(product_id)
        if view is None:
            return RedirectResponse(url="/shop", status_code=303)
        if not view.is_active and not view.in_stock:
            return RedirectResponse(
                url=f"/shop?error={i18n.t('shop.error_no_stock')}", status_code=303,
            )
        shop.set_active(product_id, not view.is_active)
        audit.record_audit(
            "product_activate" if not view.is_active else "product_deactivate",
            target=view.name,
        )
        return RedirectResponse(url="/shop", status_code=303)

    @router.post("/shop/products/{product_id}/delete")
    async def product_delete(product_id: int) -> Response:
        view = shop.get_product(product_id)
        if view is not None and shop.delete_product(product_id):
            audit.record_audit("product_delete", target=view.name)
        return RedirectResponse(url="/shop", status_code=303)

    @router.post("/shop/orders/{order_id}/status")
    async def order_status(order_id: int, status: str = Form("")) -> Response:
        if shop.set_order_status(order_id, status):
            audit.record_audit("order_status", target=str(order_id), detail=status)
        return RedirectResponse(url="/shop", status_code=303)

    return router
