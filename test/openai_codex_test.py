from pathlib import Path

import pytest

from llm_backends.openai_codex import openai_codex as codex


def test_check_if_update_needed_returns_true_when_codex_says_yes(tmp_path, monkeypatch):
    out_file = tmp_path / "codex_out" / "out.txt"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("YES")

    monkeypatch.setattr(codex, "CANDIDATE_OUT_PATHS", [out_file])

    snapshot_calls = []

    def fake_snapshot(filename, content):
        snapshot_calls.append((filename, content))

    monkeypatch.setattr(codex, "_write_snapshot", fake_snapshot)
    monkeypatch.setattr(codex, "codex_exec", lambda _: None)

    assert codex.check_if_update_needed("current text", "new text") is True
    assert snapshot_calls == [
        ("full_current_wp_page.txt", "current text"),
        ("new_text.txt", "new text"),
    ]


def test_check_if_update_needed_handles_missing_output(tmp_path, monkeypatch):
    missing_file = tmp_path / "codex_out" / "out.txt"
    monkeypatch.setattr(codex, "CANDIDATE_OUT_PATHS", [missing_file])
    monkeypatch.setattr(codex, "_write_snapshot", lambda *args: None)
    monkeypatch.setattr(codex, "codex_exec", lambda _: None)

    assert codex.check_if_update_needed("current", "new") is False


def test_update_wp_page_returns_codex_output(tmp_path, monkeypatch):
    out_file = tmp_path / "codex_out" / "out.txt"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("UPDATED ARTICLE")

    monkeypatch.setattr(codex, "CANDIDATE_OUT_PATHS", [out_file])

    snapshot_calls = []

    def fake_snapshot(filename, content):
        snapshot_calls.append((filename, content))

    monkeypatch.setattr(codex, "_write_snapshot", fake_snapshot)
    monkeypatch.setattr(codex, "codex_exec", lambda _: None)

    updated = codex.update_wp_page("current article", "new insert")
    assert updated == "UPDATED ARTICLE"
    assert snapshot_calls == [
        ("full_current_wp_page.txt", "current article"),
        ("new_text.txt", "new insert"),
    ]
