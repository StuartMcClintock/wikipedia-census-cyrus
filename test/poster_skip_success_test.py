import json
import types

from poster import _load_successful_articles, process_single_article_with_retries


def test_load_successful_articles_reads_success(tmp_path):
    log_path = tmp_path / "edit.log"
    entries = [
        {
            "timestamp": "2025-01-01T00:00:00Z",
            "article": "Good_County",
            "result": {"edit": {"result": "Success"}},
        },
        {
            "timestamp": "2025-01-01T00:00:01Z",
            "article": "Bad_County",
            "result": {"edit": {"result": "Failure"}},
        },
    ]
    log_path.write_text("\n".join(json.dumps(e) for e in entries))

    successes = _load_successful_articles(log_path)

    assert "Good_County" in successes
    assert "Bad_County" not in successes


def test_process_single_article_with_retries_skips_when_logged():
    # Should return immediately without needing a real client or args.
    skipped = set(["Skip_County"])
    dummy_args = types.SimpleNamespace()
    process_single_article_with_retries(
        "Skip_County",
        "00",
        "000",
        dummy_args,
        client=None,
        use_mini_prompt=False,
        skip_successful_articles=skipped,
    )
