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

    def fake_run(cmd, cwd=None, capture_output=False, text=False, env=None):
        calls.append(cmd)
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()

    monkeypatch.setenv("ACTIVE_MODEL", "claude-haiku-4-5")
    monkeypatch.setenv("CODEX_MODEL", "")
    monkeypatch.setattr(codex.subprocess, "run", fake_run)
    monkeypatch.setattr(
        codex,
        "_locate_codex_output",
        lambda require_nonempty=False: Path("/tmp/out.txt"),
    )

    codex.codex_exec("hello", suppress_out=True)
    assert calls
    # ensure the default codex model is used, not the Claude model
    assert calls[0][:4] == ["codex", "exec", "-m", codex.DEFAULT_CODEX_MODEL]


def test_codex_exec_retries_with_default_when_requested_model_is_chatgpt_unsupported(monkeypatch):
    calls = []

    def fake_run(cmd, cwd=None, capture_output=False, text=False, env=None):
        calls.append(cmd)

        class R:
            if len(calls) == 1:
                returncode = 1
                stdout = ""
                stderr = (
                    'ERROR: unexpected status 400 Bad Request: '
                    '{"detail":"The \'gpt-5.1-codex-max\' model is not supported when '
                    'using Codex with a ChatGPT account."}'
                )
            else:
                returncode = 0
                stdout = ""
                stderr = ""

        return R()

    monkeypatch.setattr(codex, "codex_models", codex.codex_models + ["gpt-5.1-codex-max"])
    monkeypatch.setenv("ACTIVE_MODEL", "gpt-5.1-codex-max")
    monkeypatch.delenv("CODEX_MODEL", raising=False)
    monkeypatch.setattr(codex.subprocess, "run", fake_run)
    monkeypatch.setattr(codex, "_locate_codex_output", lambda require_nonempty=False: Path("/tmp/out.txt"))

    codex.codex_exec("hello", suppress_out=True)

    assert len(calls) == 2
    assert calls[0][:4] == ["codex", "exec", "-m", "gpt-5.1-codex-max"]
    assert calls[1][:4] == ["codex", "exec", "-m", codex.DEFAULT_CODEX_MODEL]


def test_codex_exec_uses_run_artifact_dir_for_cwd_and_output(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, cwd=None, capture_output=False, text=False, env=None):
        calls.append((cmd, cwd))
        out_file = tmp_path / "codex_out" / "out.txt"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text("YES")

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    monkeypatch.setenv("ACTIVE_MODEL", codex.DEFAULT_CODEX_MODEL)
    monkeypatch.setenv(codex.RUN_ARTIFACT_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(codex.subprocess, "run", fake_run)

    codex.codex_exec("hello", suppress_out=True)

    assert calls
    assert calls[0][1] == tmp_path
    assert (tmp_path / "codex_out" / "out.txt").read_text() == "YES"


def test_codex_exec_uses_fixed_slot_two_workspace_and_output(monkeypatch):
    calls = []

    def fake_run(cmd, cwd=None, capture_output=False, text=False, env=None):
        calls.append((cmd, cwd))
        out_file = codex.BASE_DIR / "codex_out_2.txt"
        out_file.write_text("YES")

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    monkeypatch.setenv("ACTIVE_MODEL", codex.DEFAULT_CODEX_MODEL)
    monkeypatch.delenv(codex.RUN_ARTIFACT_DIR_ENV, raising=False)
    monkeypatch.setenv(codex.CODEX_OUTPUT_SLOT_ENV, "2")
    monkeypatch.setattr(codex.subprocess, "run", fake_run)

    try:
        codex.codex_exec("hello", suppress_out=True)
        assert calls
        assert calls[0][1] == codex.BASE_DIR
        assert (codex.BASE_DIR / "codex_out_2.txt").read_text() == "YES"
    finally:
        out_file = codex.BASE_DIR / "codex_out_2.txt"
        if out_file.exists():
            out_file.unlink()


def test_check_if_update_needed_slot_two_uses_alternate_prompt_filenames(monkeypatch):
    prompt_calls = []

    monkeypatch.setenv(codex.CODEX_OUTPUT_SLOT_ENV, "2")
    monkeypatch.delenv(codex.RUN_ARTIFACT_DIR_ENV, raising=False)
    monkeypatch.setattr(codex, "_write_snapshot", lambda *args: None)
    monkeypatch.setattr(codex, "_read_codex_output", lambda: "YES")

    def fake_codex_exec(prompt, suppress_out=True):
        prompt_calls.append(prompt)

    monkeypatch.setattr(codex, "codex_exec", fake_codex_exec)

    assert codex.check_if_update_needed("current text", "new text") is True
    assert "full_current_wp_page_2.txt" in prompt_calls[0]
    assert "new_text_2.txt" in prompt_calls[0]
    assert "codex_out_2.txt" in prompt_calls[0]
