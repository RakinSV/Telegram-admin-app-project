"""Публичный REST API (F73).

⚠️ ВТОРАЯ ПУБЛИЧНО ДОСТУПНАЯ ПОВЕРХНОСТЬ СИСТЕМЫ, после мини-аппа (F74).
Отсюда система становится доступна чужим программам, поэтому решения ниже
приняты от обратного: не «что бы отдать», а «что нельзя отдать никогда».

ЧЕГО В API НЕТ И НЕ БУДЕТ:

* секретов — токенов ботов, ключей ИИ, session string. Ключ API даёт доступ
  к ДАННЫМ, а не к учётным записям; иначе одна утёкшая строка отдавала бы
  вместе с ней все остальные системы владельца;
* настроек. Прочитать их — половина шага к тому, чтобы менять;
* переписки поддержки и личных данных участников сверх того, что нужно для
  интеграции. CRM отдаёт СЧЁТЧИКИ, а не выгрузку людей: «сколько у меня
  подписчиков» — интеграция, «отдай список с телефонами» — экспорт базы;
* удаления чего бы то ни было. Область `write` умеет создавать и
  публиковать, но не стирать: ошибка в чужом скрипте не должна быть
  необратимой.

ОБЛАСТЬ ПРАВ ПРОВЕРЯЕТСЯ НА КАЖДОМ ОБРАБОТЧИКЕ, а не на роутере целиком.
Роутер один, а права у методов разные, и «повесить зависимость на роутер»
означало бы либо пускать читающий ключ туда, где пишут, либо заводить два
роутера и однажды перепутать, в какой добавлять новый метод.

ОШИБКИ ОТВЕЧАЮТ ОДИНАКОВО. Нет ключа, отозван, не тот формат — везде 401 с
одним текстом: разница помогала бы перебирать.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response

from tg_repost import api_keys_repo as keys
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

API_PREFIX = "/api/v1"


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="Неверный ключ")


async def require_key(
    response: Response,
    authorization: Annotated[str | None, Header()] = None,
) -> keys.ApiKeyView:
    """Проверить ключ и частоту. Общая зависимость всех методов API.

    Ключ передаётся заголовком `Authorization: Bearer <ключ>`, а не
    параметром строки запроса: параметры оседают в логах прокси, истории
    браузера и реферерах, то есть ключ утекал бы сам собой.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorized()

    view = keys.authenticate(authorization[7:].strip())
    if view is None:
        raise _unauthorized()

    allowed, retry_after = keys.check_rate_limit(view)
    if not allowed:
        # `Retry-After` обязателен: без него вызывающий не знает, сколько
        # ждать, и начинает долбиться чаще — ровно наоборот от нужного.
        raise HTTPException(
            status_code=429,
            detail="Слишком часто",
            headers={"Retry-After": str(retry_after)},
        )
    response.headers["X-RateLimit-Limit"] = str(view.rate_limit)
    return view


def require_write(
    key: Annotated[keys.ApiKeyView, Depends(require_key)],
) -> keys.ApiKeyView:
    if key.scope != keys.SCOPE_WRITE:
        # 403, а не 401: ключ настоящий, прав не хватает. Разница здесь
        # уместна — она ничего не подсказывает о самом ключе.
        raise HTTPException(status_code=403, detail="Ключу нужна область write")
    return key


def build_api_router() -> APIRouter:
    router = APIRouter(prefix=API_PREFIX, tags=["api"])

    @router.get("/ping")
    async def ping(key: Annotated[keys.ApiKeyView, Depends(require_key)]) -> dict:
        """Проверка ключа. Отдаёт своё же описание, а не чужие данные."""
        return {"ok": True, "scope": key.scope, "name": key.name}

    @router.get("/posts")
    async def posts(
        key: Annotated[keys.ApiKeyView, Depends(require_key)],
        limit: int = 50,
    ) -> dict:
        """Опубликованные посты. Только опубликованные — черновики и
        отклонённое наружу не выходят: это внутренняя кухня редакции."""
        from tg_repost.export import export_posts

        del key
        rows = export_posts()[-max(1, min(limit, 500)):]
        return {"count": len(rows), "items": rows}

    @router.get("/stats")
    async def stats(
        key: Annotated[keys.ApiKeyView, Depends(require_key)],
        window_days: int = 30,
    ) -> dict:
        from tg_repost.scheduler.stats import compute_stats_summary

        del key
        summary = compute_stats_summary(max(1, min(window_days, 365)))
        return {
            "window_days": summary.window_days,
            "published": summary.published,
            "counted": summary.counted,
            "views_total": summary.total_views,
            "views_avg": summary.avg_views,
        }

    @router.get("/audience")
    async def audience(key: Annotated[keys.ApiKeyView, Depends(require_key)]) -> dict:
        """СЧЁТЧИКИ, А НЕ ВЫГРУЗКА ЛЮДЕЙ.

        «Сколько у меня подписчиков» — интеграция. «Отдай список с
        контактами» — экспорт базы участников через ключ, который лежит в
        чужом скрипте; для этого есть админка и живой человек за ней.
        """
        from tg_repost import subscribers_repo

        del key
        reach = subscribers_repo.reach_stats(subscribers_repo.all_user_ids())
        return {
            "total": reach.total,
            "reachable": reach.reachable,
            "never_started": reach.never_started,
            "blocked": reach.blocked,
            "unsubscribed": reach.unsubscribed,
        }

    @router.post("/posts")
    async def create_post(
        payload: dict,
        key: Annotated[keys.ApiKeyView, Depends(require_write)],
    ) -> dict:
        """Поставить пост в очередь модерации.

        ИМЕННО В МОДЕРАЦИЮ, А НЕ В ПУБЛИКАЦИЮ. Внешняя система не должна
        уметь напечатать текст в канале владельца одним запросом: ключ
        утекает вместе с чужим репозиторием, и цена ошибки — пост от лица
        канала. Одобряет по-прежнему человек.
        """
        text = str(payload.get("text", "")).strip()
        if not text:
            raise HTTPException(status_code=422, detail="Нужен непустой text")

        from tg_repost.db.models import Post, PostKind, PostStatus
        from tg_repost.db.session import session_scope

        with session_scope() as session:
            row = Post(
                kind=PostKind.SOURCE,
                original_text=text,
                rewritten_text=text,
                status=PostStatus.REWRITTEN,
            )
            session.add(row)
            session.flush()
            post_id = row.id

        logger.info("F73: ключ %s… создал пост #%d", key.prefix, post_id)
        return {"id": post_id, "status": "rewritten"}

    return router
