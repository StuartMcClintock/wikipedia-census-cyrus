import json

from app_logging.logger import log_edit_article, log_precomputed_article
from constants import DEFAULT_CODEX_MODEL


def test_log_edit_article_records_active_model(tmp_path, monkeypatch):
    monkeypatch.setenv("ACTIVE_MODEL", "gpt-5.1")

    log_path = tmp_path / "edit.log"
    log_edit_article("Sample_Town,_Test", {"edit": {"result": "Success"}}, log_path=log_path)

    entry = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert entry["article"] == "Sample_Town,_Test"
    assert entry["model"] == "gpt-5.1"
    assert entry["result"]["edit"]["result"] == "Success"


def test_log_edit_article_records_default_model_when_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("ACTIVE_MODEL", raising=False)

    log_path = tmp_path / "edit.log"
    log_edit_article("Sample_Town,_Test", {"edit": {"result": "Success"}}, log_path=log_path)

    entry = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert entry["model"] == DEFAULT_CODEX_MODEL


def test_log_precomputed_article_records_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("ACTIVE_MODEL", "gpt-5.4")

    log_path = tmp_path / "precompute.log"
    log_precomputed_article(
        "Sample_Town,_Test",
        {"section_path": "foo/bar", "section_bytes": 123},
        log_path=log_path,
    )

    entry = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert entry["article"] == "Sample_Town,_Test"
    assert entry["model"] == "gpt-5.4"
    assert entry["metadata"]["section_path"] == "foo/bar"
    assert entry["metadata"]["section_bytes"] == 123
