#!/usr/bin/env python3
"""
Move wikilinks from H3 headings into the first appropriate place in the text below.

Example:
    ===[[2010 United States census|2010 census]]===
    The 2010 census recorded ...

becomes:
    ===2010 census===
    The [[2010 United States census|2010 census]] recorded ...

Defaults to dry-run. Use --apply to edit Wikipedia.
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from credentials import WP_BOT_PASSWORD, WP_BOT_USER_AGENT, WP_BOT_USER_NAME

WIKIPEDIA_ENDPOINT = "https://en.wikipedia.org/w/api.php"
FIPS_MAPPING_DIR = ROOT_DIR / "census_api" / "fips_mappings"
STATE_TO_FIPS_PATH = FIPS_MAPPING_DIR / "state_to_fips.json"
COUNTY_FIPS_DIR = FIPS_MAPPING_DIR / "county_to_fips"
MUNICIPALITY_FIPS_DIR = FIPS_MAPPING_DIR / "municipality_to_fips"
NON_STATE_POSTALS = {"AS", "GU", "MP", "PR", "VI", "DC"}

HEADING_RE = re.compile(r"^(={3})\s*(.*?)\s*\1\s*$")
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


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


def _split_state_postals(value: str) -> List[str]:
    parts = [part for part in re.split(r"[,\s]+", value.strip()) if part]
    if any(part.upper() == "ALL" for part in parts):
        data = json.loads(STATE_TO_FIPS_PATH.read_text())
        return sorted(postal for postal in data.keys() if postal not in NON_STATE_POSTALS)
    return [part.upper() for part in parts]


def _resolve_places_path(state_postal: str, muni_type: str) -> Path:
    state_dir = MUNICIPALITY_FIPS_DIR / state_postal.upper()
    if not state_dir.exists():
        raise FileNotFoundError(f"No municipality mapping found for state '{state_postal}'.")
    places_path = state_dir / muni_type / "places.json"
    if not places_path.exists():
        available = sorted(
            p.name for p in state_dir.iterdir() if p.is_dir() and (p / "places.json").exists()
        )
        raise FileNotFoundError(
            f"No places.json for muni type '{muni_type}' in state '{state_postal}'. "
            f"Available types: {', '.join(available)}"
        )
    return places_path


def load_municipality_items(state_postal: str, muni_type: str):
    mapping = json.loads(_resolve_places_path(state_postal, muni_type).read_text())
    for name, codes in mapping.items():
        state_fips = str(codes.get("state", "")).zfill(2)
        place_fips = str(codes.get("place", "")).zfill(5)
        if not state_fips or not place_fips:
            continue
        yield name, state_fips, place_fips


def load_county_items(state_postal: str):
    path = COUNTY_FIPS_DIR / f"{state_postal.upper()}.json"
    if not path.exists():
        raise FileNotFoundError(f"No county mapping found for state '{state_postal}'.")
    mapping = json.loads(path.read_text())
    for name, code in mapping.items():
        if not isinstance(code, str) or not code.startswith("county:"):
            continue
        digits = code.split(":", 1)[1]
        if len(digits) < 5:
            continue
        state_fips = digits[:2]
        county_fips = digits[2:]
        yield name, state_fips, county_fips


def _replace_first_outside_markup(text: str, needle: str, replacement: str) -> Tuple[str, bool]:
    if not needle:
        return text, False
    n = len(text)
    m = len(needle)
    i = 0
    depth_link = 0
    depth_template = 0
    in_ref = False
    in_comment = False

    while i <= n - m:
        if text.startswith("<!--", i):
            end = text.find("-->", i + 4)
            if end == -1:
                return text, False
            i = end + 3
            continue
        if text.startswith("<ref", i):
            end_tag = text.find(">", i + 4)
            if end_tag == -1:
                return text, False
            if text[end_tag - 1] == "/":
                i = end_tag + 1
                continue
            end_ref = text.find("</ref>", end_tag + 1)
            if end_ref == -1:
                return text, False
            i = end_ref + 6
            continue

        two = text[i:i + 2]
        if two == "[[":
            depth_link += 1
            i += 2
            continue
        if two == "]]":
            depth_link = max(0, depth_link - 1)
            i += 2
            continue
        if two == "{{":
            depth_template += 1
            i += 2
            continue
        if two == "}}":
            depth_template = max(0, depth_template - 1)
            i += 2
            continue

        if depth_link == 0 and depth_template == 0:
            if text.startswith(needle, i):
                before_ok = i == 0 or not text[i - 1].isalnum()
                after_ok = i + m >= n or not text[i + m].isalnum()
                if before_ok and after_ok:
                    return text[:i] + replacement + text[i + m:], True
        i += 1
    return text, False


def _move_heading_links(block: str, links: List[Tuple[str, str]]) -> Tuple[str, int]:
    changes = 0
    if not links:
        return block, changes

    para_end = block.find("\n\n")
    first_para = block if para_end == -1 else block[:para_end]
    rest = "" if para_end == -1 else block[para_end:]

    for target, display in links:
        link_markup = f"[[{target}|{display}]]" if display != target else f"[[{target}]]"
        updated, replaced = _replace_first_outside_markup(first_para, display, link_markup)
        if replaced:
            first_para = updated
            changes += 1
            block = first_para + rest
            continue
        updated, replaced = _replace_first_outside_markup(block, display, link_markup)
        if replaced:
            block = updated
            changes += 1
            if para_end != -1:
                first_para = block[:para_end]
                rest = block[para_end:]

    return block, changes


def move_heading_links_to_text(wikitext: str) -> Tuple[str, int]:
    lines = wikitext.splitlines(keepends=True)
    i = 0
    total_changes = 0

    while i < len(lines):
        raw_line = lines[i]
        stripped = raw_line.rstrip("\n")
        match = HEADING_RE.match(stripped.strip())
        if not match:
            i += 1
            continue

        heading_text = match.group(2)
        links = []
        for link_match in WIKILINK_RE.finditer(heading_text):
            target = link_match.group(1).strip()
            display = (link_match.group(2) or target).strip()
            links.append((target, display))

        if not links:
            i += 1
            continue

        new_heading = WIKILINK_RE.sub(lambda m: (m.group(2) or m.group(1)).strip(), heading_text)
        lines[i] = f"==={new_heading}===\n"

        start = i + 1
        end = start
        while end < len(lines):
            next_line = lines[end].rstrip("\n")
            if re.match(r"^={2,6}.*={2,6}\s*$", next_line.strip()):
                break
            end += 1

        block = "".join(lines[start:end])
        updated_block, changes = _move_heading_links(block, links)
        if changes:
            total_changes += changes
            new_lines = updated_block.splitlines(keepends=True)
            lines[start:end] = new_lines
            end = start + len(new_lines)

        i = end

    return "".join(lines), total_changes


def process_article(
    article_title: str,
    client: WikipediaClient,
    apply_changes: bool,
    summary: str,
) -> Tuple[bool, Optional[str]]:
    title, wikitext = client.fetch_article_wikitext(article_title)
    if wikitext.lstrip().lower().startswith("#redirect"):
        return False, f"Skipping '{title}' because it is a redirect."

    updated_text, count = move_heading_links_to_text(wikitext)
    if count == 0:
        return False, f"No change: {title}"

    if apply_changes:
        result = client.edit_article_wikitext(title, updated_text, summary=summary)
        if result.get("edit", {}).get("result") == "Success":
            return True, f"Updated: {title} (moved {count} link(s))"
        return False, f"Edit failed: {title} -> {result}"
    return True, f"Would update: {title} (moved {count} link(s))"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Move wikilinks from H3 headers into the first paragraph below."
    )
    parser.add_argument(
        "--state-postal",
        required=True,
        help="State postal code(s), comma-separated (e.g., OK, OK,TX, or ALL).",
    )
    parser.add_argument(
        "--start-state",
        help="When using --state-postal ALL, start at this state postal code alphabetically.",
    )
    parser.add_argument(
        "--municipality-type",
        help="Municipality type folder (e.g., city, town, CDP).",
    )
    parser.add_argument(
        "--counties",
        action="store_true",
        help="Process counties instead of municipalities.",
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
        default="Move census link from heading into text",
        help="Edit summary for --apply.",
    )
    args = parser.parse_args()

    if args.counties and args.municipality_type:
        parser.error("--counties cannot be combined with --municipality-type.")
    if not args.counties and not args.municipality_type:
        parser.error("Provide --municipality-type or use --counties.")

    client = WikipediaClient(WP_BOT_USER_AGENT)
    if args.apply:
        client.login(WP_BOT_USER_NAME, WP_BOT_PASSWORD)

    total = 0
    updated = 0
    errors = 0
    started = args.start_at is None

    state_postals = _split_state_postals(args.state_postal)
    if args.start_state:
        start_state = args.start_state.upper()
        state_postals = sorted(state_postals)
        if start_state not in state_postals:
            parser.error(f"--start-state '{args.start_state}' is not in the state list.")
        state_postals = state_postals[state_postals.index(start_state):]
    for state_postal in state_postals:
        try:
            if args.counties:
                items = list(load_county_items(state_postal))
            else:
                items = list(load_municipality_items(state_postal, args.municipality_type))
        except FileNotFoundError as exc:
            errors += 1
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{timestamp} UTC] Error: {exc}")
            continue

        for name, _, _ in items:
            if not started:
                if name == args.start_at:
                    started = True
                else:
                    continue

            total += 1
            if args.limit and total > args.limit:
                break

            try:
                ok, message = process_article(
                    name.replace(" ", "_"),
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
                print(f"[{timestamp} UTC] Error: {name} -> {exc}")

            time.sleep(args.sleep)

        if args.limit and total > args.limit:
            break

    mode = "apply" if args.apply else "dry-run"
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(
        f"[{timestamp} UTC] Done ({mode}). Total processed: {total}. "
        f"Updated: {updated}. Errors: {errors}."
    )


if __name__ == "__main__":
    main()
