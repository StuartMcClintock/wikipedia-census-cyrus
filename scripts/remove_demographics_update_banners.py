#!/usr/bin/env python3
"""
Scan every article that has a successful edit logged in app_logging/logs/edit.log
and remove any "needs update" / "outdated" maintenance banner templates.

Default is dry-run. Pass --apply to actually post edits.
"""

import argparse
import difflib
import sys
import time
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from credentials import WP_BOT_PASSWORD, WP_BOT_USER_AGENT, WP_BOT_USER_NAME
from poster import WikipediaClient, _load_successful_articles

DEFAULT_EDIT_SUMMARY = "Remove outdated-content banner after 2020 census update"

BANNER_TEMPLATE_NAMES = {
    "update",
    "update inline",
    "update section",
    "outdated",
    "out of date",
    "outdated as of",
    "old statistics",
    "old data",
    "old information",
    "outdated statistics",
}

BANNER_TEXT_SUBSTRINGS = {
    "demographic",
    "census",
}


def _canonical_template_name(raw: str) -> str:
    return raw.strip().lower().replace("_", " ").replace("-", " ")


def _find_template_end(text: str, start: int) -> Optional[int]:
    """
    Given an index `start` pointing at `{{`, return the index of the first `}` of
    the matching `}}`, or None if unbalanced. Nested templates are respected.
    """
    depth = 0
    i = start
    n = len(text)
    while i < n - 1:
        pair = text[i : i + 2]
        if pair == "{{":
            depth += 1
            i += 2
        elif pair == "}}":
            depth -= 1
            if depth == 0:
                return i
            i += 2
        else:
            i += 1
    return None


def _template_is_on_own_line(text: str, start: int, end: int) -> bool:
    """
    True if the template spanning text[start:end+2] occupies a whole line on its
    own (only whitespace before it back to a newline/BOF, only whitespace after
    it forward to a newline/EOF).
    """
    i = start - 1
    while i >= 0 and text[i] in (" ", "\t"):
        i -= 1
    before_ok = i < 0 or text[i] == "\n"
    j = end + 2
    n = len(text)
    while j < n and text[j] in (" ", "\t"):
        j += 1
    after_ok = j >= n or text[j] == "\n"
    return before_ok and after_ok


def _template_mentions_demographics_or_census(template_body: str) -> bool:
    lowered = template_body.lower()
    return any(substring in lowered for substring in BANNER_TEXT_SUBSTRINGS)


def remove_banner_templates(
    wikitext: str, names: Iterable[str] = BANNER_TEMPLATE_NAMES
) -> Tuple[str, List[str]]:
    """
    Return (new_wikitext, removed_names). Templates are only removed when they
    sit on their own line; inline usage inside a sentence or paragraph is left
    untouched. When a template line is removed, its surrounding line whitespace
    and one trailing newline are consumed so no blank line is left behind.
    """
    canonical_names = {_canonical_template_name(n) for n in names}
    pieces: List[str] = []
    removed: List[str] = []
    cursor = 0
    n = len(wikitext)
    i = 0
    while i < n:
        if wikitext[i : i + 2] == "{{":
            end = _find_template_end(wikitext, i)
            if end is None:
                i += 1
                continue
            inner = wikitext[i + 2 : end]
            first_segment = inner.split("|", 1)[0]
            canonical = _canonical_template_name(first_segment)
            if (
                canonical in canonical_names
                and _template_is_on_own_line(wikitext, i, end)
                and _template_mentions_demographics_or_census(inner)
            ):
                line_start = i
                while line_start > 0 and wikitext[line_start - 1] in (" ", "\t"):
                    line_start -= 1
                after = end + 2
                while after < n and wikitext[after] in (" ", "\t"):
                    after += 1
                if after < n and wikitext[after] == "\n":
                    after += 1
                pieces.append(wikitext[cursor:line_start])
                removed.append(first_segment.strip())
                cursor = after
                i = after
                continue
            i = end + 2
        else:
            i += 1
    pieces.append(wikitext[cursor:])
    return "".join(pieces), removed


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


def _iter_articles(
    successes: Set[str],
    start_at: Optional[str],
    limit: Optional[int],
) -> Iterable[str]:
    ordered = sorted(successes, key=str.casefold)
    start_key = start_at.strip().replace(" ", "_") if start_at else None
    count = 0
    for title in ordered:
        if start_key is not None and title.casefold() < start_key.casefold():
            continue
        count += 1
        if limit is not None and count > limit:
            break
        yield title


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Remove 'needs update' / 'outdated' banner templates from articles "
            "we have successfully edited per app_logging/logs/edit.log."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually post edits. Without this flag the script is a dry-run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only inspect the first N articles (regardless of whether any changes).",
    )
    parser.add_argument(
        "--max-changes",
        type=int,
        default=None,
        help=(
            "Stop after this many articles would be/were changed. In dry-run this "
            "caps the number of 'Would remove' matches; with --apply it caps edits."
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
    args = parser.parse_args()

    successes = _load_successful_articles()
    if not successes:
        print("No successful edits found in edit.log; nothing to do.")
        return
    print(f"Loaded {len(successes)} previously-edited article(s) from edit.log.")

    client = WikipediaClient(WP_BOT_USER_AGENT)
    if args.apply:
        client.login(WP_BOT_USER_NAME, WP_BOT_PASSWORD)

    processed = 0
    changed = 0
    errors = 0

    for title in _iter_articles(successes, args.start_at, args.limit):
        processed += 1
        display = title.replace("_", " ")
        try:
            wikitext = client.fetch_article_wikitext(title)
        except Exception as exc:
            errors += 1
            print(f"Error fetching '{display}': {exc}")
            time.sleep(args.sleep)
            continue

        new_text, removed = remove_banner_templates(wikitext)
        if not removed:
            print(f"No banner: {display}")
            time.sleep(args.sleep)
            continue

        removed_label = ", ".join(f"{{{{{name}}}}}" for name in removed)
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
                print(f"Removed {removed_label} from: {display}")
            else:
                errors += 1
                print(f"Edit failed for '{display}': {result}")
        else:
            changed += 1
            print(f"Would remove {removed_label} from: {display}")

        time.sleep(args.sleep)

        if args.max_changes is not None and changed >= args.max_changes:
            print(f"Reached --max-changes={args.max_changes}; stopping.")
            break

    mode = "apply" if args.apply else "dry-run"
    print(
        f"Done ({mode}). Processed: {processed}. "
        f"{'Changed' if args.apply else 'Would change'}: {changed}. Errors: {errors}."
    )


if __name__ == "__main__":
    main()
