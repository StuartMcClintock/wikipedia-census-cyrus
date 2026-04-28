from datetime import datetime
from types import SimpleNamespace

import pytz
import pytest

from llm_backends.claude_code import claude_code as backend


def test_resolve_model_accepts_haiku_alias(monkeypatch):
    monkeypatch.setenv("ACTIVE_MODEL", "haiku")
    monkeypatch.delenv("CLAUDE_CODE_MODEL", raising=False)

    assert backend._resolve_model() == "haiku"


def test_extract_limit_reset_retry_at_uses_same_day_when_reset_is_upcoming():
    timezone = pytz.timezone("America/New_York")
    now = timezone.localize(datetime(2026, 4, 25, 11, 58))

    retry_at = backend._extract_limit_reset_retry_at(
        "You've hit your limit · resets 12pm (America/New_York)",
        now=now,
    )

    assert retry_at == timezone.localize(datetime(2026, 4, 25, 12, 1))


def test_extract_limit_reset_retry_at_rolls_to_next_day_when_needed():
    timezone = pytz.timezone("America/New_York")
    now = timezone.localize(datetime(2026, 4, 25, 12, 5))

    retry_at = backend._extract_limit_reset_retry_at(
        "You've hit your limit · resets 12pm (America/New_York)",
        now=now,
    )

    assert retry_at == timezone.localize(datetime(2026, 4, 26, 12, 1))


def test_claude_exec_waits_until_reset_then_retries(monkeypatch):
    calls = []
    sleep_calls = []
    timezone = pytz.timezone("America/New_York")
    now_values = iter(
        [
            timezone.localize(datetime(2026, 4, 25, 11, 50)),
            timezone.localize(datetime(2026, 4, 25, 11, 50)),
        ]
    )
    results = [
        SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="You've hit your limit · resets 12pm (America/New_York)",
        ),
        SimpleNamespace(returncode=0, stdout="updated article", stderr=""),
    ]

    def fake_run(cmd, cwd=None, capture_output=False, text=False):
        calls.append(cmd)
        return results.pop(0)

    monkeypatch.setenv("ACTIVE_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv(backend.CLAUDE_CODE_WAIT_FOR_LIMIT_RESET_ENV, "1")
    monkeypatch.setattr(backend, "_now_in_zone", lambda tz: next(now_values))
    monkeypatch.setattr(backend.subprocess, "run", fake_run)
    monkeypatch.setattr(backend.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    result = backend.claude_exec("hello", suppress_out=True)

    assert result == "updated article"
    assert len(calls) == 2
    assert sleep_calls[0] == pytest.approx(660.0)


def test_claude_exec_raises_limit_error_when_auto_wait_is_disabled(monkeypatch):
    monkeypatch.setenv("ACTIVE_MODEL", "claude-sonnet-4-6")
    monkeypatch.delenv(backend.CLAUDE_CODE_WAIT_FOR_LIMIT_RESET_ENV, raising=False)
    monkeypatch.setattr(
        backend.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="You've hit your limit · resets 12pm (America/New_York)",
        ),
    )

    with pytest.raises(backend.ClaudeCodeUsageLimitError) as exc_info:
        backend.claude_exec("hello", suppress_out=True)

    assert exc_info.value.retry_at is not None


def test_claude_exec_preserves_actual_cli_limit_message_when_retry_time_missing(monkeypatch):
    stderr = "You've hit your limit. Please upgrade your plan to continue."

    monkeypatch.setenv("ACTIVE_MODEL", "claude-sonnet-4-6")
    monkeypatch.delenv(backend.CLAUDE_CODE_WAIT_FOR_LIMIT_RESET_ENV, raising=False)
    monkeypatch.setattr(
        backend.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr=stderr,
        ),
    )

    with pytest.raises(backend.ClaudeCodeUsageLimitError) as exc_info:
        backend.claude_exec("hello", suppress_out=True)

    assert exc_info.value.retry_at is None
    assert stderr in str(exc_info.value)


def test_claude_exec_uses_run_artifact_dir_for_cwd_and_snapshots(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, cwd=None, capture_output=False, text=False):
        calls.append((cmd, cwd))
        return SimpleNamespace(returncode=0, stdout="YES", stderr="")

    monkeypatch.setenv("ACTIVE_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv(backend.RUN_ARTIFACT_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(backend.subprocess, "run", fake_run)

    result = backend.check_if_update_needed("current text", "new text", suppress_out=True)

    assert result is True
    assert calls
    assert calls[0][1] == tmp_path
    assert (tmp_path / "full_current_wp_page.txt").read_text() == "current text"
    assert (tmp_path / "new_text.txt").read_text() == "new text"
