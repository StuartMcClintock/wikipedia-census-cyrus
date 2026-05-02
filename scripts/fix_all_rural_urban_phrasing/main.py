#!/usr/bin/env python3
"""
Scan articles for awkward all-rural/all-urban wording inside
==Demographics== -> ===2020 census=== and replace it with natural phrasing.

Examples:
- "0.0% of residents lived in urban areas, while 100.0% lived in rural areas."
  -> "All residents lived in rural areas."
- "<0.1% of residents lived in urban areas, while 100.0% lived in rural areas."
  -> "All residents lived in rural areas."
- "100.0% of residents lived in urban areas, while 0.0% lived in rural areas."
  -> "All residents lived in urban areas."

Defaults to dry-run. Use --apply to edit Wikipedia.
"""

import argparse
import difflib
import re
import sys
import time
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parents[1]
sys.path.insert(0, str(ROOT_DIR))

from credentials import WP_BOT_PASSWORD, WP_BOT_USER_AGENT, WP_BOT_USER_NAME
from parser.parser import ParsedWikitext
from poster import WikipediaClient, _load_successful_articles

DEFAULT_EDIT_SUMMARY = "Copyedit all-rural/all-urban census phrasing"
DEFAULT_FLAGGED_LOG_PATH = SCRIPT_DIR / "flagged_articles.log"
REF_RE = r"(?:<ref[^>]*?/?>|<ref[^>]*?>.*?</ref>)"
NEAR_ZERO_RE = r"(?:0\.0%|<?0\.1%|&lt;0\.1%)"
ALL_RURAL_RE = re.compile(
    NEAR_ZERO_RE
    + r"\s+of\s+residents\s+lived\s+in\s+urban\s+areas,\s+while\s+"
    + r"100\.0%\s+lived\s+in\s+rural\s+areas\."
    + r"(?P<refs>(?:\s*"
    + REF_RE
    + r")*)",
    flags=re.IGNORECASE | re.DOTALL,
)
ALL_URBAN_RE = re.compile(
    r"100\.0%\s+of\s+residents\s+lived\s+in\s+urban\s+areas,\s+while\s+"
    + NEAR_ZERO_RE
    + r"\s+lived\s+in\s+rural\s+areas\."
    + r"(?P<refs>(?:\s*"
    + REF_RE
    + r")*)",
    flags=re.IGNORECASE | re.DOTALL,
)


def replace_all_rural_urban_phrasing(text: str) -> Tuple[str, int]:
    updated, rural_count = ALL_RURAL_RE.subn(
        lambda match: f"All residents lived in rural areas.{match.group('refs')}",
        text,
    )
    updated, urban_count = ALL_URBAN_RE.subn(
        lambda match: f"All residents lived in urban areas.{match.group('refs')}",
        updated,
    )
    return updated, rural_count + urban_count


def replace_all_rural_urban_phrasing_in_demographics_2020(
    wikitext: str,
) -> Tuple[str, int]:
    parsed = ParsedWikitext(wikitext=wikitext)
    sections = parsed.sections
    total = 0
    updated_any = False

    def heading_matches(heading: str, target: str) -> bool:
        return heading.strip().lower() == target

    def apply_to_entry(entry: Tuple[str, object]) -> Tuple[Tuple[str, object], int]:
        heading, content = entry
        if isinstance(content, list):
            new_children = []
            count = 0
            for child in content:
                updated_child, child_count = apply_to_entry(child)
                new_children.append(updated_child)
                count += child_count
            return (heading, new_children), count
        new_text, count = replace_all_rural_urban_phrasing(content)
        return (heading, new_text), count

    for idx, (heading, content) in enumerate(sections):
        if heading in {"__lead__", "__content__"}:
            continue
        if not heading_matches(heading, "demographics"):
            continue
        if not isinstance(content, list):
            continue

        new_content = []
        section_count = 0
        for child in content:
            child_heading = child[0]
            if child_heading in {"__lead__", "__content__"}:
                new_content.append(child)
                continue
            if heading_matches(child_heading, "2020 census"):
                updated_child, child_count = apply_to_entry(child)
                new_content.append(updated_child)
                section_count += child_count
            else:
                new_content.append(child)
        if section_count > 0:
            sections[idx] = (heading, new_content)
            total += section_count
            updated_any = True

    if not updated_any:
        return wikitext, 0
    return parsed.to_wikitext(), total


def _print_diff(title: str, before: str, after: str) -> None:
    diff = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=f"{title} (before)",
        tofile=f"{title} (after)",
        lineterm="",
    )
    text = "\n".join(diff).strip()
    if text:
        print(text)
    else:
        print("(no diff output)")


def _normalize_title(raw: str) -> str:
    return raw.strip().replace(" ", "_")


def _load_flagged_titles(log_path: Path = DEFAULT_FLAGGED_LOG_PATH) -> List[str]:
    if not log_path.exists():
        return []
    titles: List[str] = []
    seen = set()
    for line in log_path.read_text(encoding="utf-8").splitlines():
        title = line.strip()
        if not title or title.startswith("#"):
            continue
        normalized = _normalize_title(title)
        if normalized in seen:
            continue
        seen.add(normalized)
        titles.append(normalized)
    return titles


def _write_flagged_titles(
    titles: Sequence[str], log_path: Path = DEFAULT_FLAGGED_LOG_PATH
) -> None:
    seen = set()
    normalized_titles = []
    for title in titles:
        normalized = _normalize_title(title)
        if normalized in seen:
            continue
        seen.add(normalized)
        normalized_titles.append(normalized)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(normalized_titles)
    if text:
        text += "\n"
    log_path.write_text(text, encoding="utf-8")


def _iter_articles(
    titles: Iterable[str],
    start_at: Optional[str],
    limit: Optional[int],
) -> Iterable[str]:
    if isinstance(titles, set):
        ordered = sorted(titles, key=str.casefold)
    else:
        ordered = list(dict.fromkeys(titles))
    start_key = start_at.strip().replace(" ", "_") if start_at else None
    count = 0
    for title in ordered:
        if start_key is not None and title.casefold() < start_key.casefold():
            continue
        count += 1
        if limit is not None and count > limit:
            break
        yield title


def _format_edits_per_minute(changed: int, elapsed_seconds: float) -> str:
    if elapsed_seconds <= 0:
        rate = 0.0
    else:
        rate = changed * 60.0 / elapsed_seconds
    return f"{rate:.1f}"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Replace awkward all-rural/all-urban 2020 census phrasing in "
            "previously edited articles."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually post edits. Without this flag the script is a dry-run.",
    )
    parser.add_argument(
        "--article",
        action="append",
        default=None,
        help=(
            "Specific article title to process. May be passed multiple times. "
            "When omitted, titles come from app_logging/logs/edit.log."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only inspect the first N articles.",
    )
    parser.add_argument(
        "--max-changes",
        type=int,
        default=None,
        help=(
            "Stop after this many articles would be/were changed. In dry-run this "
            "caps matches; with --apply it caps edits."
        ),
    )
    parser.add_argument(
        "--start-at",
        type=str,
        default=None,
        help=(
            "Start processing at this title, or the first title after it "
            "alphabetically. Accepts space or underscore form."
        ),
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.5,
        help="Seconds to sleep between Wikipedia requests.",
    )
    parser.add_argument(
        "--summary",
        type=str,
        default=DEFAULT_EDIT_SUMMARY,
        help="Edit summary to use when --apply is set.",
    )
    parser.add_argument(
        "--show-diff",
        action="store_true",
        help="Print a unified diff for each article that would change.",
    )
    parser.add_argument(
        "--write-flagged-log",
        action="store_true",
        help=(
            "In dry-run mode, write the titles of articles that would be updated "
            "to the flagged-articles log."
        ),
    )
    parser.add_argument(
        "--only-flagged-articles",
        action="store_true",
        help=(
            "Only inspect article titles listed in the flagged-articles log "
            "instead of scanning all successful edits from edit.log."
        ),
    )
    parser.add_argument(
        "--flagged-log-path",
        type=Path,
        default=DEFAULT_FLAGGED_LOG_PATH,
        help=f"Path to the flagged-articles log (default: {DEFAULT_FLAGGED_LOG_PATH}).",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.apply and args.write_flagged_log:
        parser.error("--write-flagged-log can only be used in dry-run mode.")
    if args.article and args.only_flagged_articles:
        parser.error("--article cannot be combined with --only-flagged-articles.")

    if args.article:
        titles: Iterable[str] = [_normalize_title(title) for title in args.article if title.strip()]
    elif args.only_flagged_articles:
        titles = _load_flagged_titles(args.flagged_log_path)
        if not titles:
            print(f"No flagged articles found in {args.flagged_log_path}; nothing to do.")
            return
        print(f"Loaded {len(titles)} flagged article(s) from {args.flagged_log_path}.")
    else:
        titles = _load_successful_articles()
        if not titles:
            print("No successful edits found in edit.log; nothing to do.")
            return
        print(f"Loaded {len(titles)} previously-edited article(s) from edit.log.")

    client = WikipediaClient(WP_BOT_USER_AGENT)
    if args.apply:
        client.login(WP_BOT_USER_NAME, WP_BOT_PASSWORD)

    processed = 0
    changed = 0
    errors = 0
    flagged_titles: List[str] = []
    started_at = time.monotonic()

    for title in _iter_articles(titles, args.start_at, args.limit):
        processed += 1
        display = title.replace("_", " ")
        try:
            wikitext = client.fetch_article_wikitext(title)
        except Exception as exc:
            errors += 1
            print(f"Error fetching '{display}': {exc}")
            time.sleep(args.sleep)
            continue

        if wikitext.lstrip().lower().startswith("#redirect"):
            print(f"Skipping redirect: {display}")
            time.sleep(args.sleep)
            continue

        new_text, replacements = replace_all_rural_urban_phrasing_in_demographics_2020(
            wikitext
        )
        if replacements == 0:
            print(f"No change: {display}")
            time.sleep(args.sleep)
            continue

        if args.write_flagged_log:
            flagged_titles.append(title)

        if args.show_diff:
            _print_diff(display, wikitext, new_text)

        if args.apply:
            try:
                result = client.edit_article_wikitext(title, new_text, args.summary)
            except Exception as exc:
                errors += 1
                print(f"Edit error '{display}': {exc}")
                time.sleep(args.sleep)
                continue
            edit_info = result.get("edit", {}) if isinstance(result, dict) else {}
            if edit_info.get("result") == "Success":
                changed += 1
                print(f"Updated: {display} ({replacements} replacement(s))")
            else:
                errors += 1
                print(f"Edit failed for '{display}': {result}")
        else:
            changed += 1
            print(f"Would update: {display} ({replacements} replacement(s))")

        time.sleep(args.sleep)

        if args.max_changes is not None and changed >= args.max_changes:
            print(f"Reached --max-changes={args.max_changes}; stopping.")
            break

    if args.write_flagged_log:
        _write_flagged_titles(flagged_titles, args.flagged_log_path)
        print(
            f"Wrote {len(flagged_titles)} flagged article(s) to {args.flagged_log_path}."
        )

    mode = "apply" if args.apply else "dry-run"
    rate = _format_edits_per_minute(changed, time.monotonic() - started_at)
    print(
        f"Done ({mode}). Processed: {processed}. "
        f"{'Changed' if args.apply else 'Would change'}: {changed}. Errors: {errors}. "
        f"Edits/min: {rate}."
    )


if __name__ == "__main__":
    main()
