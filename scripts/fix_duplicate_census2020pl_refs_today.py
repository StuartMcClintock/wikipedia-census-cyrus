#!/usr/bin/env python3
"""
Inspect successful edits from a specific date and repair duplicate full
<ref name="Census2020PL">...</ref> definitions inside ==Demographics==.

The script is interactive by default: for each proposed fix it prints the
article title, optionally copies it to the clipboard, and waits for input.
Press Enter to apply the fix live, "s" to skip, or "q" to quit.
"""

import argparse
import difflib
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from app_logging.logger import LOG_FILE
from parser.parser import ParsedWikitext

WIKIPEDIA_ENDPOINT = "https://en.wikipedia.org/w/api.php"
DEFAULT_DATE = "2026-04-27"
DEFAULT_SUMMARY = "Fix duplicate Census2020PL citation definition in Demographics"
SECTION_SENTINELS = {"__lead__", "__content__"}
PL_REF_RE = re.compile(
    r'<ref\s+name="Census2020PL"\s*(?:>(?P<body>.*?)</ref>|/>)',
    re.IGNORECASE | re.DOTALL,
)


class WikipediaClient:
    def __init__(self, user_agent: str):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self._csrf_token = None

    def _get(self, params: Dict[str, str]):
        response = self.session.get(WIKIPEDIA_ENDPOINT, params=params)
        response.raise_for_status()
        return response

    def _post(self, data: Dict[str, str]):
        response = self.session.post(WIKIPEDIA_ENDPOINT, data=data)
        response.raise_for_status()
        return response

    def get_login_token(self) -> str:
        response = self._get(
            {
                "action": "query",
                "meta": "tokens",
                "type": "login",
                "format": "json",
            }
        )
        return response.json()["query"]["tokens"]["logintoken"]

    def login(self, username: str, password: str) -> None:
        login_token = self.get_login_token()
        response = self._post(
            {
                "action": "login",
                "lgname": username,
                "lgpassword": password,
                "lgtoken": login_token,
                "format": "json",
            }
        )
        data = response.json()
        if data.get("login", {}).get("result") != "Success":
            raise RuntimeError(f"Login failed: {data}")

    def get_csrf_token(self) -> str:
        if self._csrf_token:
            return self._csrf_token
        response = self._get(
            {
                "action": "query",
                "meta": "tokens",
                "type": "csrf",
                "format": "json",
            }
        )
        self._csrf_token = response.json()["query"]["tokens"]["csrftoken"]
        return self._csrf_token

    def fetch_article(self, title: str) -> Tuple[str, str]:
        response = self._get(
            {
                "action": "query",
                "prop": "revisions",
                "titles": title,
                "rvprop": "content",
                "rvslots": "main",
                "redirects": 1,
                "formatversion": "2",
                "format": "json",
            }
        )
        data = response.json()
        pages = data.get("query", {}).get("pages", [])
        if not pages:
            raise ValueError(f"Wikipedia API returned no page data for '{title}'.")

        page = pages[0]
        if "missing" in page:
            raise ValueError(f"Wikipedia article '{title}' does not exist.")
        if "invalidreason" in page:
            raise ValueError(
                f"Invalid article title '{title}': {page['invalidreason']}."
            )
        if "revisions" not in page:
            raise ValueError(
                f"Wikipedia API response for '{title}' is missing revisions data."
            )
        content = page["revisions"][0]["slots"]["main"]["content"]
        return page["title"], content

    def edit_article_wikitext(self, title: str, new_text: str, summary: str) -> Dict:
        response = self._post(
            {
                "action": "edit",
                "title": title,
                "text": new_text,
                "summary": summary,
                "token": self.get_csrf_token(),
                "format": "json",
                "assert": "user",
                "maxlag": "5",
            }
        )
        return response.json()


def load_successful_articles_for_date(
    date_str: str,
    log_path: Path = LOG_FILE,
) -> List[str]:
    if not log_path.exists():
        return []

    titles: List[str] = []
    seen = set()
    with log_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except Exception:
                continue

            edit = entry.get("result", {}).get("edit", {})
            if edit.get("result") != "Success":
                continue

            timestamp = (edit.get("newtimestamp") or entry.get("timestamp") or "").strip()
            if not timestamp.startswith(date_str):
                continue

            article = entry.get("article")
            if not article or article in seen:
                continue
            seen.add(article)
            titles.append(article)
    return titles


def _find_demographics_section(parsed_article: ParsedWikitext):
    for index, entry in enumerate(parsed_article.sections):
        heading = entry[0]
        if heading in SECTION_SENTINELS:
            continue
        if heading == "Demographics":
            return index, entry
    return None


def _render_single_section(section_entry) -> str:
    return ParsedWikitext(sections=[section_entry]).to_wikitext()


def _fix_duplicate_pl_refs_in_section(section_wikitext: str) -> Tuple[str, Optional[Dict[str, int]]]:
    matches = list(PL_REF_RE.finditer(section_wikitext))
    if len(matches) < 2:
        return section_wikitext, None

    full_matches = [match for match in matches if (match.group("body") or "").strip()]
    full_count = len(full_matches)
    if full_count < 2:
        return section_wikitext, None

    canonical_body = full_matches[0].group("body") or ""
    canonical_full_ref = f'<ref name="Census2020PL">{canonical_body}</ref>'

    seen_first = False

    def replacer(match: re.Match) -> str:
        nonlocal seen_first
        if not seen_first:
            seen_first = True
            return canonical_full_ref
        return '<ref name="Census2020PL"/>'

    updated = PL_REF_RE.sub(replacer, section_wikitext)
    if updated == section_wikitext:
        return section_wikitext, None

    return updated, {
        "total_refs_before": len(matches),
        "full_refs_before": full_count,
    }


def fix_duplicate_pl_refs_in_article(article_wikitext: str) -> Tuple[str, Optional[Dict[str, object]]]:
    parsed_article = ParsedWikitext(wikitext=article_wikitext)
    located = _find_demographics_section(parsed_article)
    if not located:
        return article_wikitext, None

    section_index, section_entry = located
    section_text = _render_single_section(section_entry)
    fixed_section_text, section_info = _fix_duplicate_pl_refs_in_section(section_text)
    if not section_info:
        return article_wikitext, None

    fixed_sections = ParsedWikitext(wikitext=fixed_section_text).sections
    replacement_entry = None
    for entry in fixed_sections:
        if entry[0] in SECTION_SENTINELS:
            continue
        replacement_entry = entry
        break
    if replacement_entry is None:
        raise ValueError("Fixed demographics text did not include a section heading.")

    updated_article = parsed_article.clone()
    updated_article.sections[section_index] = replacement_entry
    new_text = updated_article.to_wikitext()
    if new_text == article_wikitext:
        return article_wikitext, None

    info: Dict[str, object] = dict(section_info)
    info["section_before"] = section_text
    info["section_after"] = fixed_section_text
    return new_text, info


def _copy_to_clipboard(text: str) -> bool:
    try:
        subprocess.run(["pbcopy"], input=text, text=True, check=True)
        return True
    except Exception:
        return False


def _print_diff(title: str, before: str, after: str) -> None:
    diff = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=f"{title} (before)",
        tofile=f"{title} (after)",
        lineterm="",
    )
    text = "\n".join(diff).strip()
    print(text if text else "(no diff output)")


def _iter_titles(
    titles: Iterable[str],
    start_at: Optional[str] = None,
    limit: Optional[int] = None,
) -> Iterable[str]:
    start_key = start_at.strip().replace(" ", "_") if start_at else None
    yielded = 0
    for title in titles:
        if start_key is not None and title.casefold() < start_key.casefold():
            continue
        yielded += 1
        if limit is not None and yielded > limit:
            break
        yield title


def _count_titles(
    titles: Iterable[str],
    start_at: Optional[str] = None,
    limit: Optional[int] = None,
) -> int:
    return sum(1 for _ in _iter_titles(titles, start_at=start_at, limit=limit))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect successful edits from a given date and interactively fix "
            "duplicate full Census2020PL refs in ==Demographics==."
        )
    )
    parser.add_argument(
        "--date",
        default=DEFAULT_DATE,
        help=f"UTC date to inspect in YYYY-MM-DD format (default: {DEFAULT_DATE}).",
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        default=LOG_FILE,
        help=f"Edit log to read (default: {LOG_FILE}).",
    )
    parser.add_argument(
        "--copy-title",
        action="store_true",
        help="Copy the current article title to the clipboard with pbcopy.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only inspect the first N titles from the matching log entries.",
    )
    parser.add_argument(
        "--start-at",
        type=str,
        default=None,
        help="Start at this title, or the first title after it alphabetically.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.5,
        help="Seconds to sleep between Wikipedia requests.",
    )
    parser.add_argument(
        "--summary",
        default=DEFAULT_SUMMARY,
        help=f"Edit summary to use (default: {DEFAULT_SUMMARY}).",
    )
    parser.add_argument(
        "--show-diff",
        action="store_true",
        help="Print a unified diff of the Demographics section for each proposed fix.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not post edits; only print matching articles and proposed diffs.",
    )
    args = parser.parse_args()

    titles = load_successful_articles_for_date(args.date, log_path=args.log_path)
    if not titles:
        print(f"No successful edits found for {args.date}.")
        return

    print(f"Loaded {len(titles)} successful edit(s) from {args.date}.")
    selected_total = _count_titles(titles, start_at=args.start_at, limit=args.limit)
    print(f"Scanning {selected_total} article(s) after filters.")

    from credentials import WP_BOT_PASSWORD, WP_BOT_USER_AGENT, WP_BOT_USER_NAME

    client = WikipediaClient(WP_BOT_USER_AGENT)
    if not args.dry_run:
        client.login(WP_BOT_USER_NAME, WP_BOT_PASSWORD)

    clipboard_warned = False
    processed = 0
    candidates = 0
    applied = 0
    skipped = 0
    errors = 0

    for raw_title in _iter_titles(titles, start_at=args.start_at, limit=args.limit):
        processed += 1
        if processed == 1 or processed % 25 == 0:
            print(
                f"Heartbeat: inspected {processed - 1}/{selected_total} article(s); "
                f"now checking {raw_title.replace('_', ' ')}"
            )
        try:
            title, wikitext = client.fetch_article(raw_title)
            updated_text, info = fix_duplicate_pl_refs_in_article(wikitext)
        except Exception as exc:
            errors += 1
            print(f"Error inspecting '{raw_title.replace('_', ' ')}': {exc}")
            time.sleep(args.sleep)
            continue

        if not info:
            time.sleep(args.sleep)
            continue

        candidates += 1
        display_title = title.replace("_", " ")
        print(
            f"\n{display_title}\n"
            f"Duplicate Census2020PL fix: {info['full_refs_before']} full ref(s) "
            f"across {info['total_refs_before']} total Census2020PL occurrence(s)."
        )

        if args.copy_title:
            copied = _copy_to_clipboard(display_title)
            if copied:
                print("Copied title to clipboard.")
            elif not clipboard_warned:
                print("Clipboard copy failed; pbcopy is unavailable.")
                clipboard_warned = True

        if args.show_diff:
            _print_diff(display_title, info["section_before"], info["section_after"])

        if args.dry_run:
            time.sleep(args.sleep)
            continue

        response = input("Press Enter to apply, 's' to skip, or 'q' to quit: ").strip().lower()
        if response == "q":
            print("Stopping at user request.")
            break
        if response == "s":
            skipped += 1
            time.sleep(args.sleep)
            continue

        try:
            current_title, current_wikitext = client.fetch_article(title)
            refreshed_text, refreshed_info = fix_duplicate_pl_refs_in_article(current_wikitext)
            if not refreshed_info:
                print("No longer needs the fix; skipping.")
                skipped += 1
                time.sleep(args.sleep)
                continue
            result = client.edit_article_wikitext(
                current_title,
                refreshed_text,
                summary=args.summary,
            )
        except Exception as exc:
            errors += 1
            print(f"Error applying '{display_title}': {exc}")
            time.sleep(args.sleep)
            continue

        if result.get("edit", {}).get("result") == "Success":
            applied += 1
            print("Applied successfully.")
        else:
            errors += 1
            print(f"Edit failed: {result}")
        time.sleep(args.sleep)

    print(
        f"\nProcessed: {processed} | Candidates: {candidates} | "
        f"Applied: {applied} | Skipped: {skipped} | Errors: {errors}"
    )


if __name__ == "__main__":
    main()
