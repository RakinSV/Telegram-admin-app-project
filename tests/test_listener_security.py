"""Тест защиты от path traversal при скачивании медиа (CWE-22).

Telethon при `download_media(file=<директория>)` сам выбирает имя файла из
`DocumentAttributeFilename`, которое полностью контролируется автором поста
в канале-источнике — вредоносное имя вида `../../../evil` могло бы привести
к перезаписи произвольного файла. Фикс: скачивание в память (`file=bytes`) +
собственное безопасное имя файла; `_safe_media_extension` берёт расширение
только из `message.file.ext` (вычисляется Telethon через `mimetypes` по
MIME-типу, не из присланного имени) с доп. валидацией формата.
"""

from types import SimpleNamespace

from tg_repost.telegram.listener import _safe_media_extension


def _message_with_ext(ext: str | None) -> SimpleNamespace:
    file_obj = SimpleNamespace(ext=ext) if ext is not None else None
    return SimpleNamespace(file=file_obj)


def test_safe_extension_normal_case():
    assert _safe_media_extension(_message_with_ext(".jpg")) == ".jpg"


def test_safe_extension_no_file_falls_back():
    assert _safe_media_extension(_message_with_ext(None)) == ".bin"


def test_safe_extension_rejects_path_traversal_payload():
    # Гипотетическое вредоносное значение (Telethon его не отдаёт в норме,
    # но defense-in-depth не должен доверять формату без проверки).
    assert _safe_media_extension(_message_with_ext("../../../etc/passwd")) == ".bin"


def test_safe_extension_rejects_path_separators():
    assert _safe_media_extension(_message_with_ext("/etc/passwd")) == ".bin"
    assert _safe_media_extension(_message_with_ext("..\\windows\\system32")) == ".bin"


def test_safe_extension_rejects_too_long():
    assert _safe_media_extension(_message_with_ext(".aaaaaaaaaaaaaaaa")) == ".bin"


def test_safe_extension_rejects_non_alnum():
    assert _safe_media_extension(_message_with_ext(".jp~g")) == ".bin"


def test_safe_extension_handles_attribute_error():
    # message.file бросает исключение (например, нет media) — не должно падать.
    class Boom:
        @property
        def file(self):
            raise RuntimeError("no media")

    assert _safe_media_extension(Boom()) == ".bin"
