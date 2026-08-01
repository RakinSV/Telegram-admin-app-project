"""Редакция из двух агентов (F40, rewriter/editorial.py): цикл черновик →
рецензия → веб-сверка → правка, устойчивость к сбоям и оплате."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tg_repost.config import get_settings, invalidate_settings_cache
from tg_repost.rewriter import editorial
from tg_repost.rewriter.client import RewriteResult


@pytest.fixture(autouse=True)
def _clean_settings(monkeypatch):
    for key in (
        "EDITORIAL_ENABLED", "EDITORIAL_MAX_ROUNDS",
        "EDITORIAL_WEB_VERIFY_ENABLED", "EDITORIAL_WEB_VERIFY_MAX_CLAIMS",
    ):
        monkeypatch.delenv(key, raising=False)
    invalidate_settings_cache()
    yield
    invalidate_settings_cache()


def _result(text: str, tokens: int = 10) -> RewriteResult:
    return RewriteResult(text=text, prompt_tokens=tokens, completion_tokens=tokens)


def _client(*, draft: str, reviews: list[str], revisions: list[str]) -> AsyncMock:
    """Мок клиента: rewrite() отдаёт черновик, rewrite_with_prompt() —
    поочерёдно рецензии и правки (рецензия и правка чередуются в цикле)."""
    client = AsyncMock()
    client.rewrite = AsyncMock(return_value=_result(draft))
    # В цикле вызовы идут: review, revise, review, revise... собираем вперемешку.
    sequence: list[RewriteResult] = []
    for i in range(max(len(reviews), len(revisions))):
        if i < len(reviews):
            sequence.append(_result(reviews[i]))
        if i < len(revisions):
            sequence.append(_result(revisions[i]))
    client.rewrite_with_prompt = AsyncMock(side_effect=sequence)
    return client


# --- разбор ответа редактора ---


def test_parse_verdict_ok():
    approved, notes, claims = editorial._parse_editor_output("ВЕРДИКТ: OK")
    assert approved is True
    assert claims == []


def test_parse_verdict_revise():
    approved, _, _ = editorial._parse_editor_output("ВЕРДИКТ: ПРАВИТЬ\n1. слабый лид")
    assert approved is False


def test_parse_conflicting_verdict_is_cautious_revise():
    # Если модель написала оба вердикта — выбираем осторожное «править».
    approved, _, _ = editorial._parse_editor_output("ВЕРДИКТ: OK\nно ВЕРДИКТ: ПРАВИТЬ")
    assert approved is False


def test_extract_claims_from_check_block():
    text = "ВЕРДИКТ: ПРАВИТЬ\n1. цифра\nПРОВЕРИТЬ:\n- крупнейший банк 2025\n- рост 50%\n"
    claims = editorial._extract_claims(text)
    assert claims == ["крупнейший банк 2025", "рост 50%"]


# --- полный цикл ---


async def test_approved_first_pass_returns_draft_no_revision(monkeypatch):
    monkeypatch.setenv("EDITORIAL_MAX_ROUNDS", "1")
    invalidate_settings_cache()
    client = _client(draft="черновик", reviews=["ВЕРДИКТ: OK"], revisions=[])
    res = await editorial.editorial_rewrite(
        client, original="источник", link_content="", prompt_name="default", language=None,
    )
    assert res.text == "черновик"
    assert res.rounds_used == 0
    assert res.notes == editorial._APPROVED_NOTE
    assert client.rewrite_with_prompt.await_count == 1  # только рецензия


async def test_revise_when_editor_asks(monkeypatch):
    monkeypatch.setenv("EDITORIAL_MAX_ROUNDS", "1")
    monkeypatch.setenv("EDITORIAL_WEB_VERIFY_ENABLED", "false")
    invalidate_settings_cache()
    client = _client(
        draft="черновик",
        reviews=["ВЕРДИКТ: ПРАВИТЬ\n1. выдумана цифра 50%"],
        revisions=["исправленный текст"],
    )
    res = await editorial.editorial_rewrite(
        client, original="источник", link_content="", prompt_name="default", language=None,
    )
    assert res.text == "исправленный текст"
    assert res.rounds_used == 1
    assert "выдумана цифра" in res.notes
    assert client.rewrite_with_prompt.await_count == 2  # рецензия + правка


async def test_zero_rounds_is_draft_only(monkeypatch):
    monkeypatch.setenv("EDITORIAL_MAX_ROUNDS", "0")
    invalidate_settings_cache()
    client = _client(draft="черновик", reviews=["ВЕРДИКТ: ПРАВИТЬ\n1. что-то"], revisions=[])
    res = await editorial.editorial_rewrite(
        client, original="источник", link_content="", prompt_name="default", language=None,
    )
    assert res.text == "черновик"
    assert res.rounds_used == 0
    client.rewrite_with_prompt.assert_not_awaited()  # рецензии не было вовсе


async def test_billing_error_on_review_propagates(monkeypatch):
    monkeypatch.setenv("EDITORIAL_MAX_ROUNDS", "1")
    invalidate_settings_cache()
    client = AsyncMock()
    client.rewrite = AsyncMock(return_value=_result("черновик"))
    client.rewrite_with_prompt = AsyncMock(
        side_effect=RuntimeError("Error code: 402 - Недостаточно средств на балансе")
    )
    with pytest.raises(RuntimeError):
        await editorial.editorial_rewrite(
            client, original="источник", link_content="", prompt_name="default", language=None,
        )


async def test_non_billing_error_on_review_keeps_draft(monkeypatch):
    monkeypatch.setenv("EDITORIAL_MAX_ROUNDS", "1")
    invalidate_settings_cache()
    client = AsyncMock()
    client.rewrite = AsyncMock(return_value=_result("черновик"))
    client.rewrite_with_prompt = AsyncMock(side_effect=TimeoutError("Timed out"))
    res = await editorial.editorial_rewrite(
        client, original="источник", link_content="", prompt_name="default", language=None,
    )
    assert res.text == "черновик"  # флапнувшая рецензия не теряет хороший черновик
    assert res.rounds_used == 0


async def test_empty_revision_keeps_previous_draft(monkeypatch):
    monkeypatch.setenv("EDITORIAL_MAX_ROUNDS", "1")
    monkeypatch.setenv("EDITORIAL_WEB_VERIFY_ENABLED", "false")
    invalidate_settings_cache()
    client = _client(
        draft="черновик", reviews=["ВЕРДИКТ: ПРАВИТЬ\n1. правь"], revisions=["   "],
    )
    res = await editorial.editorial_rewrite(
        client, original="источник", link_content="", prompt_name="default", language=None,
    )
    assert res.text == "черновик"  # пустая правка не затирает черновик


async def test_web_verify_feeds_findings_into_revision(monkeypatch):
    monkeypatch.setenv("EDITORIAL_MAX_ROUNDS", "1")
    monkeypatch.setenv("EDITORIAL_WEB_VERIFY_ENABLED", "true")
    invalidate_settings_cache()

    from tg_repost.enrichment.search import SearchResult

    fake_search = AsyncMock()
    fake_search.configured = True
    fake_search.search = AsyncMock(return_value=[
        SearchResult(title="Банк N", url="https://ex.com/a", description="крупнейший в 2025"),
    ])
    monkeypatch.setattr(editorial, "get_search_client", lambda: fake_search)

    client = _client(
        draft="черновик",
        reviews=["ВЕРДИКТ: ПРАВИТЬ\n1. проверь\nПРОВЕРИТЬ:\n- крупнейший банк 2025"],
        revisions=["исправлено по находке"],
    )
    res = await editorial.editorial_rewrite(
        client, original="источник", link_content="", prompt_name="default", language=None,
    )
    assert res.text == "исправлено по находке"
    fake_search.search.assert_awaited()  # веб-сверка была
    # находки попали в промпт правки
    revise_prompt = client.rewrite_with_prompt.await_args_list[1].args[0]
    assert "находки_из_интернета" in revise_prompt
    assert "https://ex.com/a" in revise_prompt


async def test_web_verify_skipped_when_search_not_configured(monkeypatch):
    monkeypatch.setenv("EDITORIAL_MAX_ROUNDS", "1")
    monkeypatch.setenv("EDITORIAL_WEB_VERIFY_ENABLED", "true")
    invalidate_settings_cache()

    fake_search = AsyncMock()
    fake_search.configured = False
    monkeypatch.setattr(editorial, "get_search_client", lambda: fake_search)

    client = _client(
        draft="черновик",
        reviews=["ВЕРДИКТ: ПРАВИТЬ\nПРОВЕРИТЬ:\n- что-то"],
        revisions=["правка без находок"],
    )
    res = await editorial.editorial_rewrite(
        client, original="источник", link_content="", prompt_name="default", language=None,
    )
    assert res.text == "правка без находок"
    revise_prompt = client.rewrite_with_prompt.await_args_list[1].args[0]
    assert "находки_из_интернета" not in revise_prompt


def test_editorial_defaults():
    settings = get_settings()
    assert settings.editorial_enabled is True
    assert settings.editorial_max_rounds == 1
    assert settings.editorial_web_verify_enabled is True
