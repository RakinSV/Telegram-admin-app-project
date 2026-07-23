"""Джобы пайплайна (F06 рерайт, оркестрация модерации).

Один периодический тик:
  1. Берёт посты `new` → рерайтит → `rewritten` (F06).
  2. Отправляет `rewritten` владельцу на модерацию (F07),
     либо при AUTO_POST_ENABLED — сразу одобряет и публикует (F11, Фаза 2).
"""

from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path

from telegram.ext import Application

from tg_repost import languages
from tg_repost.ads.injector import inject_native_ad
from tg_repost.config import get_settings
from tg_repost.covers.dispatcher import generate_cover
from tg_repost.db.models import Post, PostCoverVariant, PostRewriteVariant, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.enrichment.enricher import enrich_post, enrichment_enabled_for
from tg_repost.enrichment.link_content import (
    download_link_image,
    extract_article_urls,
    fetch_link_content,
)
from tg_repost.logging_conf import get_logger
from tg_repost.rewriter.client import RewriterClient, resolve_style_prompt
from tg_repost.telegraph.article import publish_article
from tg_repost.telegraph.client import TelegraphError
from tg_repost.telegram.moderation_bot import send_pending_for_approval
from tg_repost.telegram.publisher import (
    publish_post,
    resolve_target_languages_for_post,
)

logger = get_logger(__name__)

# Защита от опечатки в настройке (500 вместо 5) — каждый вариант это отдельный
# платный вызов LLM/генератора картинок, не даём случайно разорить бюджет.
_MAX_VARIANTS = 10


async def _save_link_image(post_id: int, image_url: str) -> str | None:
    """Скачать обложку статьи по ссылке и сохранить в media_dir. None при
    любой проблеме (не критично — рерайт продолжается без картинки, F18
    авто-обложка ниже подхватит, если включена)."""
    downloaded = await download_link_image(image_url)
    if downloaded is None:
        return None
    data, ext = downloaded

    settings = get_settings()
    media_dir = Path(settings.media_dir)
    dest = media_dir / f"link_{post_id}_{uuid.uuid4().hex}{ext}"

    def _save() -> None:
        media_dir.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    await asyncio.to_thread(_save)
    return str(dest)


_URL_RE = re.compile(r"https?://\S+")
# Служебные строки RSS-стабов, которые не несут смысла, но накручивают длину.
_BOILERPLATE_RE = re.compile(r"(?im)^\s*(information published\.?|read more\.?)\s*$")


def effective_source_chars(original: str, link_text: str) -> int:
    """Сколько ОСМЫСЛЕННОГО материала есть для рерайта.

    Из оригинала выкидываются ссылки и служебные строки-заглушки («Information
    published»): у RSS-стаба CVE это почти весь объём, и без вычистки такой
    заголовок ложно выглядел бы «достаточным». `link_text` (текст статьи по
    ссылке) добавляется как есть — если статью прочитали, материала заведомо
    хватает.
    """
    stripped = _BOILERPLATE_RE.sub("", _URL_RE.sub("", original or ""))
    return len("".join(stripped.split())) + len((link_text or "").strip())


async def rewrite_new_posts(rewriter: RewriterClient, batch: int = 5) -> None:
    """Рерайтнуть посты со статусом `new` (F06)."""
    with session_scope() as session:
        post_ids = [
            row[0]
            for row in session.query(Post.id)
            .filter(Post.status == PostStatus.NEW)
            .order_by(Post.created_at.asc())
            .limit(batch)
            .all()
        ]

    for post_id in post_ids:
        # Резервируем пост: new → rewriting. Заодно читаем стиль источника (F15)
        # и решаем, нужно ли обогащение (F16).
        with session_scope() as session:
            post = session.get(Post, post_id)
            if post is None or post.status != PostStatus.NEW:
                continue
            post.set_status(PostStatus.REWRITING)
            original = post.original_text
            style = post.source.style_profile if post.source else None
            enrich = enrichment_enabled_for(post.source)
            source_media_path = post.media_path
            has_media = bool(source_media_path)
            post_format = (post.source.post_format if post.source else None) or "post"

        prompt_name = resolve_style_prompt(style)

        # F16-доп. — переход по первой ссылке в посте: без этого рерайт
        # неизбежно синонимайзит короткий тизер вместо пересказа по существу
        # (см. enrichment/link_content.py). Ошибка/недоступность ссылки не
        # должна ронять рерайт — тогда просто работаем по одному посту, как раньше.
        link_text = ""
        link_image_url: str | None = None
        link_url: str | None = None
        if get_settings().fetch_link_content_enabled:
            # Перебираем кандидатов, а не берём первую попавшуюся ссылку:
            # первая может быть промо-ссылкой канала (отсеивается в
            # extract_article_urls), битой или закрытой пейволом — тогда
            # шанс есть у следующей. Число попыток ограничено там же.
            for url in extract_article_urls(original):
                link_content = await fetch_link_content(url)
                if link_content:
                    link_text = link_content.text
                    link_image_url = link_content.image_url
                    link_url = link_content.url
                    break

        # Страж от выдумок: если по ссылке НЕ прочитана статья, а в оригинале
        # только заголовок — рерайтить нечего, и модель начинает изобретать
        # (см. rewrite_min_source_chars). Отсеиваем ДО обращения к модели: и
        # деньги на выдумку не тратятся, и очередь не засоряется. Порог 0 —
        # защита выключена.
        min_source = get_settings().rewrite_min_source_chars
        if min_source > 0 and effective_source_chars(original, link_text) < min_source:
            logger.info(
                "Пост %s отсеян: недостаточно материала для рерайта "
                "(только заголовок, статья по ссылке не прочитана)", post_id,
            )
            with session_scope() as session:
                post = session.get(Post, post_id)
                if post:
                    post.set_status(
                        PostStatus.FILTERED_OUT,
                        reason="недостаточно материала: только заголовок, статья не прочитана",
                    )
            continue

        # Формат «статья»: рерайт пишет лонгрид, он уезжает на Telegraph, а в
        # канал идёт тизер со ссылкой. Ветка отдельная и ДО генерации
        # вариантов: у статьи один текст (варианты выбирают между короткими
        # формулировками поста, а не между версиями лонгрида) и свой промпт.
        if post_format == "article" and get_settings().telegraph_enabled:
            try:
                teaser, article_url, full_text = await publish_article(
                    rewriter, original, link_text, link_image_url,
                )
            except TelegraphError as exc:
                # Страницы нет — значит и ссылки в посте нет, публиковать
                # нечего. Помечаем FAILED с внятной причиной, но текст
                # СОХРАНЯЕМ: работа LLM уже оплачена, владелец увидит её при
                # модерации и решит сам.
                logger.error("Статья для поста %s не опубликована: %s", post_id, exc)
                with session_scope() as session:
                    post = session.get(Post, post_id)
                    if post:
                        post.set_status(PostStatus.FAILED, reason=f"Telegraph: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001
                logger.error("Рерайт статьи для поста %s провален: %s", post_id, exc)
                with session_scope() as session:
                    post = session.get(Post, post_id)
                    if post:
                        post.set_status(PostStatus.FAILED, reason=f"ошибка статьи: {exc}")
                continue

            with session_scope() as session:
                post = session.get(Post, post_id)
                if post:
                    post.rewritten_text = teaser
                    post.telegraph_url = article_url
                    post.link_source_url = link_url
                    post.link_content_chars = len(link_text) if link_text else 0
                    post.set_status(PostStatus.REWRITTEN)
            logger.info("Пост %s — статья: %s", post_id, article_url)
            continue

        # F06-доп. — N вариантов текста (settings.rewrite_variant_count),
        # владелец выбирает лучший при модерации (бот/веб-админка). Каждый
        # вариант — отдельный вызов LLM, генерируются последовательно (не
        # asyncio.gather) — параллельные вызовы на один пост раньше времени
        # упирались бы в rate-limit провайдера сильнее, чем последовательные
        # (см. antiban-комментарии в других местах пайплайна). Провал ОДНОГО
        # варианта из нескольких не фатален — фатально только если не вышло
        # получить НИ ОДНОГО (сохраняет прежнее поведение при variant_count=1).
        rewrite_count = max(1, min(get_settings().rewrite_variant_count, _MAX_VARIANTS))
        # Языки берутся у ЦЕЛЕВЫХ ГРУПП поста: один источник может кормить и
        # русские, и англоязычные каналы, и одним текстом их не обслужить.
        # Пустой список (публиковать пока некуда) = один проход без указания
        # языка, модель ответит на языке исходника — прежнее поведение.
        target_languages: list[str | None] = list(
            resolve_target_languages_for_post(post_id)
        ) or [None]
        rewrite_texts: list[str] = []
        rewrite_tokens_list: list[int] = []
        rewrite_languages: list[str] = []
        last_exc: Exception | None = None
        for language in target_languages:
            for _ in range(rewrite_count):
                try:
                    result = await rewriter.rewrite(
                        original, prompt_name=prompt_name, link_content=link_text,
                        language=language,
                    )
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    logger.warning("Вариант рерайта поста %s не удался: %s", post_id, exc)
                    continue
                # Пустой ответ модели — это НЕ успех, хотя исключения и не
                # было: модель могла отказаться отвечать или вернуть только
                # пробелы. Раньше такой «вариант» проходил дальше, пост
                # получал статус rewritten с пустым текстом, на модерации
                # показывался оригинал (фолбэк в превью) — и владелец одобрял
                # пустоту, узнавая о проблеме только когда публикация падала.
                if not result.text.strip():
                    last_exc = last_exc or ValueError("модель вернула пустой текст")
                    logger.warning("Вариант рерайта поста %s пуст — отбрасываю", post_id)
                    continue
                rewrite_texts.append(result.text)
                rewrite_tokens_list.append(result.total_tokens)
                rewrite_languages.append(languages.normalize(language))

        if not rewrite_texts:
            logger.error("Рерайт поста %s провален (все варианты): %s", post_id, last_exc)
            with session_scope() as session:
                post = session.get(Post, post_id)
                if post:
                    post.set_status(PostStatus.FAILED, reason=f"ошибка рерайта: {last_exc}")
            continue

        # F16 — добор источников (не критично: при ошибке просто без блока).
        # Один общий блок на ВСЕ варианты — источники не зависят от того,
        # какими словами переписан пост, второй LLM-вызов на вариант был бы
        # чистым расточительством токенов.
        if enrich:
            block = await enrich_post(rewriter, original)
            if block:
                rewrite_texts = [f"{t}\n{block}" for t in rewrite_texts]

        # Обложки: сперва реальная картинка статьи по ссылке (F16-доп.) — она
        # информативнее универсальной AI/стоковой, идёт вариантом №1; F18
        # авто-обложка добирает остальные N-1.
        #
        # Своё медиа у поста больше не отменяет генерацию (настройка
        # `cover_replace_source_media`): раньше отменяло, и на модерацию
        # приходила чужая картинка — как правило с текстом и watermark'ами,
        # то есть ровно то, чего мы в обложках избегаем. Оригинал не теряется,
        # а становится ПОСЛЕДНИМ вариантом: вернуться к нему можно кнопками
        # ◀▶ прямо при модерации.
        settings = get_settings()
        cover_count = max(1, min(settings.cover_variant_count, _MAX_VARIANTS))
        generate_over_media = settings.cover_replace_source_media
        cover_paths: list[str] = []
        if not has_media or generate_over_media:
            if link_image_url:
                link_cover = await _save_link_image(post_id, link_image_url)
                if link_cover:
                    cover_paths.append(link_cover)
            for _ in range(max(0, cover_count - len(cover_paths))):
                cover_path = await generate_cover(rewriter, original)
                if cover_path:
                    cover_paths.append(cover_path)
        if has_media and cover_paths and source_media_path:
            cover_paths.append(source_media_path)

        with session_scope() as session:
            post = session.get(Post, post_id)
            if post:
                post.rewritten_text = rewrite_texts[0]
                post.rewrite_tokens = sum(rewrite_tokens_list)
                post.active_rewrite_variant_index = 0
                # Что реально прочитано по ссылке — видно при модерации.
                # Без этого слабый рерайт неотличим: «по полной статье и всё
                # равно плохо» против «статью не открыли, переписан тизер».
                post.link_source_url = link_url
                post.link_content_chars = len(link_text) if link_text else 0
                for idx, text in enumerate(rewrite_texts):
                    session.add(PostRewriteVariant(
                        post_id=post_id, variant_index=idx, text=text,
                        tokens=rewrite_tokens_list[idx],
                        language=rewrite_languages[idx],
                    ))
                if cover_paths:
                    post.media_path = cover_paths[0]
                    post.active_cover_variant_index = 0
                    for idx, path in enumerate(cover_paths):
                        session.add(PostCoverVariant(
                            post_id=post_id, variant_index=idx, media_path=path,
                        ))
                post.set_status(PostStatus.REWRITTEN)
        logger.info(
            "Пост %s рерайчен (стиль=%s, вариантов текста=%d, вариантов обложки=%d, "
            "ссылка=%s, обогащение=%s, %d токенов)",
            post_id, prompt_name, len(rewrite_texts), len(cover_paths),
            bool(link_text), enrich, sum(rewrite_tokens_list),
        )


async def _auto_publish_rewritten(application: Application) -> None:
    """Режим без модерации: rewritten → approved (→ posted, если без слотов).

    Если включено расписание по слотам (F11), посты остаются `approved` в
    очереди — публикация произойдёт в слот (см. scheduler/posting.py).
    """
    settings = get_settings()
    with session_scope() as session:
        post_ids = [
            row[0]
            for row in session.query(Post.id)
            .filter(Post.status == PostStatus.REWRITTEN)
            .order_by(Post.created_at.asc())
            .limit(10)
            .all()
        ]
    for post_id in post_ids:
        with session_scope() as session:
            post = session.get(Post, post_id)
            if post is None or post.status != PostStatus.REWRITTEN:
                continue
            post.set_status(PostStatus.APPROVED)
        if not settings.scheduled_posting_enabled:
            await publish_post(application.bot, post_id)


async def pipeline_tick(rewriter: RewriterClient, application: Application) -> None:
    """Один проход пайплайна: рерайт + реклама (F21) + (модерация | авто-постинг)."""
    settings = get_settings()
    try:
        await rewrite_new_posts(rewriter)
        await inject_native_ad(rewriter)
        if settings.auto_post_enabled:
            await _auto_publish_rewritten(application)
        else:
            await send_pending_for_approval(application)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ошибка в pipeline_tick: %s", exc)
