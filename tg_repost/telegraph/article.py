"""Сборка и публикация поста в формате «статья» (лонгрид на Telegraph).

Отличие от обычного поста: рерайт пишет полный текст без потолка 900
символов, он уезжает на telegra.ph, а в канал идёт короткий тизер со
ссылкой — Telegram разворачивает её через Instant View.
"""

from __future__ import annotations

from tg_repost.config import get_settings
from tg_repost.logging_conf import get_logger
from tg_repost.rewriter.client import RewriterClient, build_rewrite_prompt
from tg_repost.telegraph.client import create_page
from tg_repost.telegraph.nodes import extract_title, image_node, markdown_to_nodes

logger = get_logger(__name__)

ARTICLE_PROMPT = "article"


def build_teaser(title: str, body: str, url: str, limit: int) -> str:
    """Текст поста-тизера: заголовок, первый абзац и ссылка на статью.

    Первый абзац берётся как есть, а не пересказывается отдельным вызовом
    LLM — лишний запрос на каждый пост того не стоит, а первый абзац статьи
    и так пишется как введение (см. промпт `article.txt`).

    `limit` считается ВМЕСТЕ со ссылкой: она должна уместиться обязательно,
    иначе тизер теряет смысл. Поэтому под неё резервируется место, и режется
    именно текст.
    """
    first_para = ""
    for chunk in (body or "").split("\n\n"):
        cleaned = " ".join(line.strip() for line in chunk.strip().splitlines())
        # Пропускаем подзаголовки и код — вводным абзацем они не являются.
        if cleaned and not cleaned.startswith(("#", "```", ">", "-", "*")):
            first_para = cleaned
            break

    head = f"{title}\n\n{first_para}".strip() if first_para else title.strip()
    room = limit - len(url) - 2  # 2 символа на перевод строки перед ссылкой
    if room > 0 and len(head) > room:
        # room - 1: место под само многоточие, иначе тизер вылезает за лимит
        # ровно на один символ (поймано тестом).
        head = head[:room - 1].rstrip() + "…"
    return f"{head}\n\n{url}".strip()


async def publish_article(
    rewriter: RewriterClient,
    original_text: str,
    link_content: str = "",
    link_image_url: str | None = None,
) -> tuple[str, str, str]:
    """Написать статью, опубликовать её и вернуть (тизер, url, полный текст).

    Бросает `TelegraphError`, если страницу создать не удалось — вызывающий
    код решает, что делать: статьи нет, значит и ссылки в посте нет.
    """
    settings = get_settings()
    prompt = build_rewrite_prompt(ARTICLE_PROMPT, original_text, link_content)
    result = await rewriter.rewrite_with_prompt(prompt)

    title, body = extract_title(result.text)
    if not title:
        title = "Без заголовка"
    nodes = markdown_to_nodes(body)

    # Картинка исходной статьи — первой, как обложка лонгрида. Свои
    # сгенерированные обложки сюда не годятся: Telegraph принимает только
    # URL, а они лежат локально в media/ без публичного адреса (см.
    # `nodes.image_node`). Их место — обложка поста-тизера в канале.
    if link_image_url:
        nodes.insert(0, image_node(link_image_url))

    url = await create_page(title, nodes)
    teaser = build_teaser(title, body, url, settings.article_teaser_max_chars)
    logger.info(
        "Статья готова: «%s», %d узлов, тизер %d символов",
        title[:60], len(nodes), len(teaser),
    )
    return teaser, url, result.text
