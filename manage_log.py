import argparse
import json
from pathlib import Path

from app_logging.logger import LOG_FILE
from app_logging.logger import LOG_DIR


def remove_entries(article_title: str, log_path: Path = LOG_FILE) -> int:
    """
    Remove log entries matching the given article title. Returns the count removed.
    """
    if not log_path.exists():
        return 0
    removed = 0
    kept_lines = []
    target = article_title.replace(" ", "_")
    with log_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except Exception:
                kept_lines.append(line)
                continue
            if entry.get("article") == target:
                removed += 1
                continue
            kept_lines.append(line)
    if removed:
        log_path.write_text("".join(kept_lines), encoding="utf-8")
    return removed


def _load_successes(log_path: Path = LOG_FILE) -> set:
    successes = set()
    if not log_path.exists():
        return successes
    with log_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                entry = json.loads(line)
                edit = entry.get("result", {}).get("edit", {})
                if edit.get("result") == "Success":
                    article = entry.get("article")
                    if article:
                        successes.add(article)
            except Exception:
                continue
    return successes


def main():
    parser = argparse.ArgumentParser(
        description="Remove log entries for a specific county/article from app_logging/logs/edit.log"
    )
    parser.add_argument(
        "--remove-log",
        dest="title",
        required=False,
        help="Article title (e.g., 'Beaver County, Utah')",
    )
    parser.add_argument(
        "--count",
        action="store_true",
        help="Show total number of successfully logged counties",
    )
    args = parser.parse_args()
    if args.count:
        try:
            successes = _load_successes()
            print(f"Total successfully logged counties: {len(successes)}")
        except Exception as exc:
            print(f"Failed to count successes: {exc}")
    if args.title:
        count = remove_entries(args.title)
        print(f"Removed {count} matching log entr{'y' if count == 1 else 'ies'}.")


if __name__ == "__main__":
    main()
