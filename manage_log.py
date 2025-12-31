import argparse
import json
from pathlib import Path

from app_logging.logger import LOG_FILE


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


def main():
    parser = argparse.ArgumentParser(
        description="Remove log entries for a specific county/article from app_logging/logs/edit.log"
    )
    parser.add_argument(
        "--remove-log",
        dest="title",
        required=True,
        help="Article title (e.g., 'Beaver County, Utah')",
    )
    args = parser.parse_args()
    count = remove_entries(args.title)
    print(f"Removed {count} matching log entr{'y' if count == 1 else 'ies'}.")


if __name__ == "__main__":
    main()
