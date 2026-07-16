"""Санитайзинг текста из недоверенных внешних источников (F01/F08-доп.).

Названия каналов/чатов (Source.channel_title, DiscoveredChat.title,
TargetGroup.title, если заполнено через авто-обнаружение) приходят от
Telegram напрямую из чужого канала/чата — полностью подконтрольны его
владельцу, не самому пользователю системы. Jinja2 экранирует их от XSS
автоматически (см. webui/app.py), но НЕ защищает от Unicode-трюков
(bidi-override, zero-width-символы), которыми можно визуально подделать
название в списках /sources и /targets (например, заставить чужой канал
выглядеть как уже знакомый — найдено на security-ревью).
"""

from __future__ import annotations

# Строим набор "опасных" кодпоинтов через chr(), а не литералами в
# исходнике: сами эти символы невидимы/управляющие, и хранить их как
# литералы в .py-файле — верный способ однажды словить незаметное
# повреждение файла инструментом, который "поправит" кодировку.
_ZERO_WIDTH_RANGE = range(0x200B, 0x200F + 1)  # zero-width space/joiners, LTR/RTL marks
_BIDI_OVERRIDE_RANGE = range(0x202A, 0x202E + 1)  # LRE/RLE/PDF/LRO/RLO
_BIDI_ISOLATE_RANGE = range(0x2066, 0x2069 + 1)  # LRI/RLI/FSI/PDI
_ASCII_CONTROL_RANGE = [
    c for c in range(0x00, 0x20) if c not in (0x09, 0x0A, 0x0D)  # оставляем tab/LF/CR
]

_DANGEROUS_CHARS = frozenset(
    chr(cp)
    for cp in (
        *_ZERO_WIDTH_RANGE, *_BIDI_OVERRIDE_RANGE, *_BIDI_ISOLATE_RANGE, *_ASCII_CONTROL_RANGE,
    )
)


def strip_bidi_control_chars(text: str | None) -> str | None:
    """Убрать zero-width/bidi-override/управляющие символы из названия
    канала/чата перед сохранением в БД. None/пустая строка после очистки —
    тоже None (не хранить пустой мусор вместо title)."""
    if not text:
        return None
    cleaned = "".join(ch for ch in text if ch not in _DANGEROUS_CHARS).strip()
    return cleaned or None
