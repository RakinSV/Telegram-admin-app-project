"""Тесты журнала изменений веб-админки (F23, Фаза 5.4)."""

from tg_repost.db.models import AuditLog
from tg_repost.db.session import session_scope
from tg_repost.webui import audit


def _clear_audit_log() -> None:
    with session_scope() as session:
        session.query(AuditLog).delete()


def test_record_audit_writes_row():
    _clear_audit_log()
    audit.record_audit("source_add", target="@durov", detail="создан")
    entries = audit.list_audit_log()
    assert len(entries) == 1
    assert entries[0].action == "source_add"
    assert entries[0].target == "@durov"
    assert entries[0].detail == "создан"
    assert entries[0].actor == "admin"


def test_record_audit_target_and_detail_optional():
    _clear_audit_log()
    audit.record_audit("component_start")
    entries = audit.list_audit_log()
    assert len(entries) == 1
    assert entries[0].target is None
    assert entries[0].detail is None


def test_list_audit_log_newest_first():
    _clear_audit_log()
    audit.record_audit("first")
    audit.record_audit("second")
    audit.record_audit("third")
    entries = audit.list_audit_log()
    assert [e.action for e in entries] == ["third", "second", "first"]


def test_list_audit_log_respects_limit():
    _clear_audit_log()
    for i in range(5):
        audit.record_audit(f"action_{i}")
    entries = audit.list_audit_log(limit=2)
    assert len(entries) == 2
    assert entries[0].action == "action_4"


def test_record_audit_truncates_long_detail():
    _clear_audit_log()
    long_detail = "x" * 1000
    audit.record_audit("post_edit", target="#1", detail=long_detail)
    entries = audit.list_audit_log()
    assert len(entries[0].detail) == audit._MAX_DETAIL_LEN + 1  # +1 for the "…" marker
    assert entries[0].detail.endswith("…")


def test_record_audit_never_stores_secret_values():
    """Регрессия/инвариант: запись о смене секрета несёт только имя ключа
    (target), НИКОГДА само значение — секреты в этой системе write-only по
    умолчанию, показ значения возможен только через отдельный пароль-гейт
    (см. settings.html / settings_store.set_secret / app.py::secrets_reveal)."""
    _clear_audit_log()
    audit.record_audit("secret_set", target="openai_api_key")
    entries = audit.list_audit_log()
    assert entries[0].target == "openai_api_key"
    assert entries[0].detail is None
