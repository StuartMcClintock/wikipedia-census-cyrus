#!/usr/bin/env python3
"""
Fix duplicate args and inline param formatting in {{US Census population}} templates.

Pulls candidate articles from a Wikipedia category (default:
Category:Articles_using_duplicate_arguments_in_template_calls).

Defaults to dry-run. Use --apply to edit Wikipedia.
"""

import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from credentials import WP_BOT_PASSWORD, WP_BOT_USER_AGENT, WP_BOT_USER_NAME
from municipality.muni_type_classifier import find_template_block

WIKIPEDIA_ENDPOINT = "https://en.wikipedia.org/w/api.php"
US_CENSUS_TEMPLATE_RE = re.compile(r"\{\{\s*US Census population", re.IGNORECASE)


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
        params = {
            "action": "query",
            "meta": "tokens",
            "type": "login",
            "format": "json",
        }
        response = self._get(params)
        return response.json()["query"]["tokens"]["logintoken"]

    def login(self, username: str, password: str) -> None:
        login_token = self.get_login_token()
        payload = {
            "action": "login",
            "lgname": username,
            "lgpassword": password,
            "lgtoken": login_token,
            "format": "json",
        }
        response = self._post(payload)
        data = response.json()
        if data.get("login", {}).get("result") != "Success":
            raise RuntimeError(f"Login failed: {data}")

    def get_csrf_token(self) -> str:
        if self._csrf_token:
            return self._csrf_token
        params = {
            "action": "query",
            "meta": "tokens",
            "type": "csrf",
            "format": "json",
        }
        response = self._get(params)
        self._csrf_token = response.json()["query"]["tokens"]["csrftoken"]
        return self._csrf_token

    def fetch_article_wikitext(self, title: str) -> Tuple[str, str]:
        params = {
            "action": "query",
            "prop": "revisions",
            "titles": title,
            "rvprop": "content",
            "rvslots": "main",
            "redirects": 1,
            "formatversion": "2",
            "format": "json",
        }
        response = self._get(params)
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
        return page["title"], page["revisions"][0]["slots"]["main"]["content"]

    def edit_article_wikitext(self, title: str, new_text: str, summary: str) -> Dict:
        token = self.get_csrf_token()
        payload = {
            "action": "edit",
            "title": title,
            "text": new_text,
            "summary": summary,
            "token": token,
            "format": "json",
            "assert": "user",
            "maxlag": "5",
        }
        response = self._post(payload)
        return response.json()


def _split_param_line(line: str) -> List[str]:
    if "|" not in line:
        return [line]
    stripped = line.lstrip()
    if not stripped.startswith("|"):
        return [line]
    indent = line[: len(line) - len(stripped)]
    positions: List[int] = []
    depth_template = 0
    depth_link = 0
    i = 0
    while i < len(line):
        two = line[i:i + 2]
        if two == "{{":
            depth_template += 1
            i += 2
            continue
        if two == "}}":
            depth_template = max(0, depth_template - 1)
            i += 2
            continue
        if two == "[[":
            depth_link += 1
            i += 2
            continue
        if two == "]]":
            depth_link = max(0, depth_link - 1)
            i += 2
            continue
        if line[i] == "|" and depth_template == 0 and depth_link == 0:
            positions.append(i)
        i += 1
    if len(positions) <= 1:
        return [line]
    segments = []
    for idx, pos in enumerate(positions):
        end = positions[idx + 1] if idx + 1 < len(positions) else len(line)
        segment = line[pos:end].rstrip()
        segments.append(indent + segment.lstrip())
    return segments


def _split_template_line(line: str) -> List[str]:
    if "|" not in line:
        return [line]
    stripped = line.lstrip()
    if stripped.startswith("{{"):
        first_pipe = line.find("|")
        if first_pipe == -1:
            return [line]
        prefix = line[:first_pipe].rstrip()
        rest = line[first_pipe:]
        segments = _split_param_line(rest)
        indent = re.match(r"^(\s*)", line).group(1)
        normalized = [prefix] + [indent + seg.lstrip() for seg in segments]
        return normalized
    return _split_param_line(line)


def normalize_us_census_template(template: str) -> Tuple[str, bool]:
    lines = template.splitlines()
    changed = False
    normalized: List[str] = []
    for line in lines:
        parts = _split_template_line(line)
        if len(parts) > 1:
            changed = True
        normalized.extend(parts)
    return "\n".join(normalized), changed


def _dedupe_2020_lines(lines: List[str]) -> Tuple[List[str], bool]:
    indices = [i for i, line in enumerate(lines) if re.match(r"^\s*\|\s*2020\s*=", line, flags=re.IGNORECASE)]
    if len(indices) <= 1:
        return lines, False
    keep_index = indices[0]
    for idx in indices:
        match = re.search(r"\d[\d,]*", lines[idx])
        if match:
            keep_index = idx
            break
    keep_line = lines[keep_index]
    for idx in sorted(indices, reverse=True):
        lines.pop(idx)
    insert_at = indices[0]
    lines.insert(insert_at, keep_line)
    return lines, True


def fix_us_census_population_template(template: str) -> Tuple[str, bool]:
    normalized, changed = normalize_us_census_template(template)
    lines = normalized.splitlines()
    lines, deduped = _dedupe_2020_lines(lines)
    return "\n".join(lines), changed or deduped


def fix_article_us_census_templates(wikitext: str) -> Tuple[str, int]:
    updated = []
    cursor = 0
    total_changes = 0
    while True:
        match = US_CENSUS_TEMPLATE_RE.search(wikitext, cursor)
        if not match:
            updated.append(wikitext[cursor:])
            break
        start = match.start()
        block = find_template_block(wikitext, start)
        if not block:
            updated.append(wikitext[cursor:])
            break
        end = block[1]
        updated.append(wikitext[cursor:start])
        template = wikitext[start:end]
        new_template, changed = fix_us_census_population_template(template)
        if changed:
            total_changes += 1
        updated.append(new_template)
        cursor = end
    return "".join(updated), total_changes


def fetch_category_members(category_title: str, limit: Optional[int] = None) -> List[str]:
    titles: List[str] = []
    params = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": category_title,
        "cmlimit": "500",
        "cmnamespace": "0",
        "format": "json",
    }
    headers = {"User-Agent": WP_BOT_USER_AGENT}
    while True:
        response = requests.get(
            WIKIPEDIA_ENDPOINT, params=params, timeout=30, headers=headers
        )
        response.raise_for_status()
        data = response.json()
        members = data.get("query", {}).get("categorymembers", [])
        for item in members:
            title = item.get("title")
            if title:
                titles.append(title.replace(" ", "_"))
                if limit and len(titles) >= limit:
                    return titles
        cont = data.get("continue", {})
        if not cont:
            break
        params.update(cont)
    return titles


def process_article(
    article_title: str,
    client: WikipediaClient,
    apply_changes: bool,
    summary: str,
) -> Tuple[bool, Optional[str]]:
    title, wikitext = client.fetch_article_wikitext(article_title)
    if wikitext.lstrip().lower().startswith("#redirect"):
        return False, f"Skipping '{title}' because it is a redirect."
    updated_text, changes = fix_article_us_census_templates(wikitext)
    if changes == 0:
        return False, f"No change: {title}"
    if apply_changes:
        result = client.edit_article_wikitext(title, updated_text, summary=summary)
        if result.get("edit", {}).get("result") == "Success":
            return True, f"Updated: {title} (fixed census template args)"
        return False, f"Edit failed: {title} -> {result}"
    return True, f"Would update: {title} (fixed census template args)"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix duplicate args in US Census population templates using a category list."
    )
    parser.add_argument(
        "--category",
        default="Category:Articles_using_duplicate_arguments_in_template_calls",
        help="Category to pull article titles from.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Edit Wikipedia pages instead of dry-run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N pages.",
    )
    parser.add_argument(
        "--start-at",
        type=str,
        default=None,
        help="Start processing at this exact page name.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.5,
        help="Seconds to sleep between requests.",
    )
    parser.add_argument(
        "--summary",
        type=str,
        default="Fix duplicate args in US Census population template",
        help="Edit summary for --apply.",
    )
    args = parser.parse_args()

    client = WikipediaClient(WP_BOT_USER_AGENT)
    if args.apply:
        client.login(WP_BOT_USER_NAME, WP_BOT_PASSWORD)

    titles = fetch_category_members(args.category, limit=args.limit)
    total = 0
    updated = 0
    errors = 0
    started = args.start_at is None

    for title in titles:
        if not started:
            if title == args.start_at:
                started = True
            else:
                continue
        total += 1
        try:
            ok, message = process_article(
                title,
                client,
                apply_changes=args.apply,
                summary=args.summary,
            )
            if message:
                timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{timestamp} UTC] {message}")
            if ok:
                updated += 1
        except Exception as exc:
            errors += 1
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{timestamp} UTC] Error: {title} -> {exc}")

        time.sleep(args.sleep)

    mode = "apply" if args.apply else "dry-run"
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(
        f"[{timestamp} UTC] Done ({mode}). Total processed: {total}. "
        f"Updated: {updated}. Errors: {errors}."
    )


if __name__ == "__main__":
    main()
