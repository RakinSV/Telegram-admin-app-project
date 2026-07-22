"""Разметка рерайта → узлы Telegraph (чистые функции, без сети).

Telegraph принимает НЕ HTML-строку, а DOM в виде JSON: либо голая строка
(текстовый узел), либо `{"tag": ..., "attrs": ..., "children": [...]}`.
Это принципиально удобнее parse_mode: экранировать ничего не нужно, любые
`<`, `&` и кавычки в тексте статьи остаются обычным текстом и инъекцией
стать не могут (ровно та проблема, из-за которой parse_mode выключен в
`telegram/publisher.py`).

Из разрешённых Telegraph тегов используем подмножество, которое реально
умеет выдавать LLM по нашему промпту `prompts/article.txt`. Заголовков h1/h2
у Telegraph НЕТ — только h3/h4, поэтому «##» маппится в h3, «###» в h4.
"""

from __future__ import annotations

import re
from typing import Any

# Узел Telegraph: строка (текст) или словарь с тегом.
Node = str | dict[str, Any]

_FENCE_RE = re.compile(r"^```[^\n]*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_UL_RE = re.compile(r"^\s*[-*•]\s+(.*)$")
_OL_RE = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_QUOTE_RE = re.compile(r"^>\s?(.*)$")
_HR_RE = re.compile(r"^\s*(?:---+|\*\*\*+|___+)\s*$")

# Инлайн-разметка. Порядок важен: `код` разбирается ПЕРВЫМ, иначе ** и _
# внутри кода съедаются как форматирование.
_INLINE_RE = re.compile(
    r"(?P<code>`[^`\n]+`)"
    r"|(?P<bold>\*\*[^*\n]+\*\*)"
    r"|(?P<italic>(?<![\w*])\*[^*\n]+\*(?![\w*]))"
    r"|(?P<mdlink>\[[^\]\n]+\]\((?:https?://)[^)\s]+\))"
    r"|(?P<url>https?://[^\s<>\"']+)"
)
_URL_TRAILING_PUNCT = ").,!?;:»\""


def extract_title(text: str) -> tuple[str, str]:
    """Разделить ответ модели на заголовок статьи и тело.

    Промпт просит первой строкой «# Заголовок» — Telegraph требует title
    отдельным полем, внутри контента его быть не должно (иначе заголовок
    продублируется на странице).

    Если модель забыла «#», заголовком становится первая непустая строка:
    падать из-за формата ответа нельзя, статья важнее.
    """
    lines = (text or "").strip().splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        match = _HEADING_RE.match(stripped)
        title = match.group(2).strip() if match else stripped
        return title, "\n".join(lines[i + 1:]).strip()
    return "", ""


def _parse_inline(text: str) -> list[Node]:
    """Текст с инлайн-разметкой → список узлов (строки и теги)."""
    nodes: list[Node] = []
    pos = 0
    for match in _INLINE_RE.finditer(text):
        if match.start() > pos:
            nodes.append(text[pos:match.start()])
        kind = match.lastgroup
        raw = match.group(0)
        if kind == "code":
            nodes.append({"tag": "code", "children": [raw[1:-1]]})
        elif kind == "bold":
            nodes.append({"tag": "strong", "children": [raw[2:-2]]})
        elif kind == "italic":
            nodes.append({"tag": "em", "children": [raw[1:-1]]})
        elif kind == "mdlink":
            label, _, rest = raw[1:].partition("](")
            nodes.append({
                "tag": "a", "attrs": {"href": rest[:-1]}, "children": [label],
            })
        else:  # голый URL
            url = raw.rstrip(_URL_TRAILING_PUNCT)
            nodes.append({"tag": "a", "attrs": {"href": url}, "children": [url]})
            # Съеденную пунктуацию возвращаем в текст, иначе «(см. ссылку)»
            # теряет закрывающую скобку.
            trailing = raw[len(url):]
            if trailing:
                nodes.append(trailing)
        pos = match.end()
    if pos < len(text):
        nodes.append(text[pos:])
    return nodes or [text]


def _flush_paragraph(buf: list[str], out: list[Node]) -> None:
    if not buf:
        return
    text = " ".join(line.strip() for line in buf).strip()
    buf.clear()
    if text:
        out.append({"tag": "p", "children": _parse_inline(text)})


def _flush_list(items: list[str], tag: str, out: list[Node]) -> None:
    if not items:
        return
    out.append({
        "tag": tag,
        "children": [{"tag": "li", "children": _parse_inline(i)} for i in items],
    })
    items.clear()


def markdown_to_nodes(text: str) -> list[Node]:
    """Тело статьи (markdown-подобный вывод LLM) → узлы Telegraph.

    Блоки кода вырезаются ПЕРВЫМИ и целиком: внутри них не должно работать
    ни инлайн-форматирование, ни склейка строк в абзац — иначе отступы кода
    схлопнутся, а `*` и `_` в коде превратятся в теги.
    """
    out: list[Node] = []
    para: list[str] = []
    ul_items: list[str] = []
    ol_items: list[str] = []
    quote: list[str] = []
    code: list[str] | None = None

    def flush_all() -> None:
        _flush_paragraph(para, out)
        _flush_list(ul_items, "ul", out)
        _flush_list(ol_items, "ol", out)
        if quote:
            out.append({
                "tag": "blockquote",
                "children": _parse_inline(" ".join(q.strip() for q in quote)),
            })
            quote.clear()

    for raw_line in (text or "").splitlines():
        line = raw_line.rstrip()

        if _FENCE_RE.match(line.strip()):
            if code is None:  # открываем блок кода
                flush_all()
                code = []
            else:  # закрываем
                out.append({
                    "tag": "pre",
                    "children": [{"tag": "code", "children": ["\n".join(code)]}],
                })
                code = None
            continue

        if code is not None:
            code.append(raw_line)
            continue

        if not line.strip():
            flush_all()
            continue

        if _HR_RE.match(line):
            flush_all()
            out.append({"tag": "hr"})
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush_all()
            # У Telegraph только h3/h4 — h1/h2 не существует.
            tag = "h3" if len(heading.group(1)) <= 2 else "h4"
            out.append({"tag": tag, "children": _parse_inline(heading.group(2).strip())})
            continue

        quoted = _QUOTE_RE.match(line)
        if quoted:
            _flush_paragraph(para, out)
            _flush_list(ul_items, "ul", out)
            _flush_list(ol_items, "ol", out)
            quote.append(quoted.group(1))
            continue

        ordered = _OL_RE.match(line)
        if ordered:
            _flush_paragraph(para, out)
            _flush_list(ul_items, "ul", out)
            ol_items.append(ordered.group(1).strip())
            continue

        bullet = _UL_RE.match(line)
        if bullet:
            _flush_paragraph(para, out)
            _flush_list(ol_items, "ol", out)
            ul_items.append(bullet.group(1).strip())
            continue

        _flush_list(ul_items, "ul", out)
        _flush_list(ol_items, "ol", out)
        para.append(line)

    # Незакрытый ``` — не повод терять код: отдаём как есть.
    if code is not None:
        out.append({
            "tag": "pre", "children": [{"tag": "code", "children": ["\n".join(code)]}],
        })
    flush_all()
    return out


def image_node(url: str, caption: str = "") -> Node:
    """Картинка (при наличии подписи — обёрнутая в figure с figcaption).

    Telegraph вставляет картинки ТОЛЬКО по URL — своего аплоада в
    официальном API нет. Значит сюда годятся адреса из исходной статьи, а
    не локальные файлы из `media/` (у них публичного адреса нет).
    """
    img: Node = {"tag": "img", "attrs": {"src": url}}
    if not caption:
        return {"tag": "figure", "children": [img]}
    return {
        "tag": "figure",
        "children": [img, {"tag": "figcaption", "children": [caption]}],
    }
