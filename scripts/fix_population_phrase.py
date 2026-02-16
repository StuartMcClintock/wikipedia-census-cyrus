#!/usr/bin/env python3
"""
Scan municipality articles (from FIPS mappings) for phrases like:
"had a population of X people, Y households, and Z families residing in the city"
and replace them with:
"had a population of X, with Y households and Z families residing in the city".

Edits are limited to the ===2020 census=== H3 inside the ==Demographics== H2.
Defaults to dry-run. Use --apply to edit Wikipedia.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, Tuple

import requests

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from credentials import WP_BOT_PASSWORD, WP_BOT_USER_AGENT, WP_BOT_USER_NAME
from parser.parser import ParsedWikitext

WIKIPEDIA_ENDPOINT = "https://en.wikipedia.org/w/api.php"
MUNICIPALITY_FIPS_DIR = (
    ROOT_DIR / "census_api" / "fips_mappings" / "municipality_to_fips"
)

REF_RE = r"(?:<ref[^>]*?/?>|<ref[^>]*?>.*?</ref>)"
TAIL_RE = r"(?P<tail>(?:residing|resided)(?:\s+in(?:\s+[^\\n\\.;:,]+)?)?)"
POP_PHRASE_RE = re.compile(
    r"(?P<prefix>had a population of\s+)"
    r"(?P<pop>[\d,]+)"
    r"(?P<pop_ref>\s*" + REF_RE + r")?"
    r"\s+people,\s+"
    r"(?P<hh>[\d,]+)"
    r"(?P<hh_ref>\s*" + REF_RE + r")?"
    r"\s+households,\s+and\s+"
    r"(?P<fam>[\d,]+)"
    r"(?P<fam_ref>\s*" + REF_RE + r")?"
    r"\s+families(?:\s+" + TAIL_RE + r")?",
    flags=re.IGNORECASE | re.DOTALL,
)

THERE_WERE_PHRASE_RE = re.compile(
    r"(?P<prefix>there\s+were\s+)"
    r"(?P<pop>[\d,]+)"
    r"(?P<pop_ref>\s*" + REF_RE + r")?"
    r"\s+people,\s+"
    r"(?P<hh>[\d,]+)"
    r"(?P<hh_ref>\s*" + REF_RE + r")?"
    r"\s+households,\s+and\s+"
    r"(?P<fam>[\d,]+)"
    r"(?P<fam_ref>\s*" + REF_RE + r")?"
    r"\s+families(?:\s+" + TAIL_RE + r")?",
    flags=re.IGNORECASE | re.DOTALL,
)

POPULATION_OF_PHRASE_RE = re.compile(
    r"(?P<prefix>population of\s+)"
    r"(?P<pop>[\d,]+)"
    r"(?P<pop_ref>\s*" + REF_RE + r")?"
    r"\s+people,\s+"
    r"(?P<hh>[\d,]+)"
    r"(?P<hh_ref>\s*" + REF_RE + r")?"
    r"\s+households,\s+and\s+"
    r"(?P<fam>[\d,]+)"
    r"(?P<fam_ref>\s*" + REF_RE + r")?"
    r"\s+families(?:\s+" + TAIL_RE + r")?",
    flags=re.IGNORECASE | re.DOTALL,
)

PEOPLE_PHRASE_RE = re.compile(
    r"(?P<prefix>^|[\\s\\(\\[])"  # keep leading whitespace or open paren/bracket
    r"(?P<pop>[\d,]+)"
    r"(?P<pop_ref>\s*" + REF_RE + r")?"
    r"\s+people,\s+"
    r"(?P<hh>[\d,]+)"
    r"(?P<hh_ref>\s*" + REF_RE + r")?"
    r"\s+households,\s+and\s+"
    r"(?P<fam>[\d,]+)"
    r"(?P<fam_ref>\s*" + REF_RE + r")?"
    r"\s+families(?:\s+" + TAIL_RE + r")?",
    flags=re.IGNORECASE | re.DOTALL,
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


def load_municipality_titles(state_postal: str, muni_type: str) -> Iterable[str]:
    mapping = json.loads(_resolve_places_path(state_postal, muni_type).read_text())
    return sorted(mapping.keys())


def replace_population_phrase(text: str) -> Tuple[str, int]:
    def normalize_tail(tail: str) -> str:
        if not tail:
            return ""
        lowered = tail.lower()
        if lowered.startswith("resided in"):
            tail = "residing in" + tail[len("resided in"):]
        return tail

    def repl(match: re.Match) -> str:
        pop_ref = match.group("pop_ref") or ""
        hh_ref = match.group("hh_ref") or ""
        fam_ref = match.group("fam_ref") or ""
        tail = normalize_tail(match.group("tail")) if "tail" in match.groupdict() else ""
        tail = f" {tail}" if tail else ""
        raw_prefix = match.group("prefix")
        prefix = raw_prefix.lower()
        if prefix.startswith("there"):
            lead = "there was a population of "
        elif prefix.startswith("population of"):
            lead = raw_prefix
        elif prefix.startswith("had a population of"):
            lead = raw_prefix
        else:
            lead = raw_prefix + "there was a population of "
        return (
            f"{lead}"
            f"{match.group('pop')}{pop_ref}, with "
            f"{match.group('hh')}{hh_ref} households and "
            f"{match.group('fam')}{fam_ref} families{tail}"
        )

    updated, count_a = POP_PHRASE_RE.subn(repl, text)
    updated, count_b = THERE_WERE_PHRASE_RE.subn(repl, updated)
    updated, count_c = POPULATION_OF_PHRASE_RE.subn(repl, updated)
    updated, count_d = PEOPLE_PHRASE_RE.subn(repl, updated)
    return updated, count_a + count_b + count_c + count_d


def replace_population_phrase_in_demographics_2020(wikitext: str) -> Tuple[str, int]:
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
        new_text, count = replace_population_phrase(content)
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix population/household/family phrasing for municipality articles."
    )
    parser.add_argument(
        "--state-postal",
        required=True,
        help="State postal code (e.g., TN).",
    )
    parser.add_argument(
        "--municipality-type",
        required=True,
        help="Municipality type folder (e.g., city, town, CDP).",
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
        help="Start processing at this exact 'City, Tennessee' name.",
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
        default="Copyedit population/household/family sentence",
        help="Edit summary for --apply.",
    )
    args = parser.parse_args()

    client = WikipediaClient(WP_BOT_USER_AGENT)
    if args.apply:
        client.login(WP_BOT_USER_NAME, WP_BOT_PASSWORD)

    total = 0
    updated = 0
    errors = 0
    started = args.start_at is None

    for name in load_municipality_titles(args.state_postal, args.municipality_type):
        if not started:
            if name == args.start_at:
                started = True
            else:
                continue

        total += 1
        if args.limit and total > args.limit:
            break

        try:
            title, wikitext = client.fetch_article_wikitext(name)
            new_text, count = replace_population_phrase_in_demographics_2020(wikitext)
            if count == 0:
                print(f"No change: {title}")
            else:
                if args.apply:
                    result = client.edit_article_wikitext(
                        title, new_text, summary=args.summary
                    )
                    if result.get("edit", {}).get("result") == "Success":
                        updated += 1
                        print(f"Updated: {title} ({count} replacement(s))")
                    else:
                        errors += 1
                        print(f"Edit failed: {title} -> {result}")
                else:
                    updated += 1
                    print(f"Would update: {title} ({count} replacement(s))")
        except Exception as exc:
            errors += 1
            print(f"Error: {name} -> {exc}")

        time.sleep(args.sleep)

    mode = "apply" if args.apply else "dry-run"
    print(
        f"Done ({mode}). Total processed: {total}. "
        f"Updated: {updated}. Errors: {errors}."
    )


if __name__ == "__main__":
    main()
