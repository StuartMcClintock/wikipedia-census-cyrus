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
    monkeypatch.setattr(codex, "codex_exec", lambda *args, **kwargs: None)

    assert codex.check_if_update_needed("current text", "new text") is True
    assert snapshot_calls == [
        ("full_current_wp_page.txt", "current text"),
        ("new_text.txt", "new text"),
    ]


def test_check_if_update_needed_handles_missing_output(tmp_path, monkeypatch):
    missing_file = tmp_path / "codex_out" / "out.txt"
    monkeypatch.setattr(codex, "CANDIDATE_OUT_PATHS", [missing_file])
    monkeypatch.setattr(codex, "_write_snapshot", lambda *args: None)
    monkeypatch.setattr(codex, "codex_exec", lambda *args, **kwargs: None)

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
    monkeypatch.setattr(codex, "codex_exec", lambda *args, **kwargs: None)

    updated = codex.update_wp_page("current article", "new insert")
    assert updated == "UPDATED ARTICLE"
    assert snapshot_calls == [
        ("full_current_wp_page.txt", "current article"),
        ("new_text.txt", "new insert"),
    ]


def test_codex_exec_falls_back_when_active_model_not_codex(monkeypatch):
    calls = []

    def fake_run(cmd, cwd=None, capture_output=False, text=False):
        calls.append(cmd)
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()

    monkeypatch.setenv("ACTIVE_MODEL", "claude-haiku-4-5")
    monkeypatch.setenv("CODEX_MODEL", "")
    monkeypatch.setattr(codex.subprocess, "run", fake_run)

    codex.codex_exec("hello", suppress_out=True)
    assert calls
    # ensure the default codex model is used, not the Claude model
    assert calls[0][:4] == ["codex", "exec", "-m", codex.DEFAULT_CODEX_MODEL]
