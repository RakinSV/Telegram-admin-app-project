"""Тесты санитайзера названий каналов/чатов (F01/F08-доп., security-ревью):
защита /sources и /targets от визуальной подделки через zero-width/
bidi-override Unicode-символы в чужом channel_title/DiscoveredChat.title."""

from __future__ import annotations

from tg_repost.text_sanitize import strip_bidi_control_chars


def test_strip_bidi_control_chars_leaves_normal_text_untouched():
    assert strip_bidi_control_chars("My Channel Title") == "My Channel Title"


def test_strip_bidi_control_chars_removes_zero_width_space():
    zwsp = chr(0x200B)
    assert strip_bidi_control_chars(f"Hello{zwsp}World") == "HelloWorld"


def test_strip_bidi_control_chars_removes_rtl_override():
    rlo = chr(0x202E)
    assert strip_bidi_control_chars(f"A{rlo}B") == "AB"


def test_strip_bidi_control_chars_removes_bidi_isolate():
    lri = chr(0x2066)
    assert strip_bidi_control_chars(f"X{lri}Y") == "XY"


def test_strip_bidi_control_chars_removes_ascii_control():
    assert strip_bidi_control_chars("A\x00B\x1fC") == "ABC"


def test_strip_bidi_control_chars_keeps_tab_and_newline():
    assert strip_bidi_control_chars("A\tB") == "A\tB"


def test_strip_bidi_control_chars_none_stays_none():
    assert strip_bidi_control_chars(None) is None


def test_strip_bidi_control_chars_empty_string_becomes_none():
    assert strip_bidi_control_chars("") is None


def test_strip_bidi_control_chars_whitespace_only_after_cleanup_becomes_none():
    zwsp = chr(0x200B)
    assert strip_bidi_control_chars(f"  {zwsp}  ") is None
