#!/usr/bin/env python3
"""
Scan municipality articles and move any <ref> tags that appear immediately
after the {{US Census population}} template into the template's footnote parameter.

Example transformation:
    {{US Census population
    | footnote = text<ref>...</ref>
    }}
<ref>{{Cite web...}}</ref>

becomes:
    {{US Census population
    | footnote = text<ref>...</ref><ref>{{Cite web...}}</ref>
    }}

Defaults to dry-run. Use --apply to edit Wikipedia.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, Tuple

import requests

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from credentials import WP_BOT_PASSWORD, WP_BOT_USER_AGENT, WP_BOT_USER_NAME

WIKIPEDIA_ENDPOINT = "https://en.wikipedia.org/w/api.php"
MUNICIPALITY_FIPS_DIR = (
    ROOT_DIR / "census_api" / "fips_mappings" / "municipality_to_fips"
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


def load_municipality_titles(state_postal: str, muni_type: str):
    mapping = json.loads(_resolve_places_path(state_postal, muni_type).read_text())
    return sorted(mapping.keys())


def _split_state_postals(value: str):
    return [part for part in re.split(r"[,\s]+", value.strip()) if part]


def move_census_refs_to_footnote(wikitext: str) -> Tuple[str, int]:
    """
    Find {{US Census population}} templates and move any trailing <ref> tags
    into the footnote parameter.

    Returns (updated_wikitext, number_of_changes)
    """
    # Pattern to match {{US Census population...}} template
    # We need to handle nested braces and refs inside the template
    template_pattern = re.compile(
        r'(\{\{US Census population\s*\n'  # Template opening
        r'(?:[^{}]|\{\{[^{}]*\}\}|\{[^{}]*\})*?'  # Template body (allow nested braces)
        r'\}\})'  # Template closing
        r'(\s*<ref[^>]*>.*?</ref>)',  # Trailing ref tag(s)
        re.IGNORECASE | re.DOTALL
    )

    changes = 0

    def replace_template(match):
        nonlocal changes
        template = match.group(1)
        trailing_refs = match.group(2)

        # Find the footnote parameter in the template
        footnote_pattern = re.compile(
            r'(\|\s*footnote\s*=\s*)(.*?)(\n\s*\||\n\s*\}\})',
            re.DOTALL
        )

        footnote_match = footnote_pattern.search(template)

        if footnote_match:
            # Append the trailing ref to the existing footnote value
            prefix = footnote_match.group(1)
            existing_footnote = footnote_match.group(2)
            suffix = footnote_match.group(3)

            # Remove trailing whitespace from existing footnote
            existing_footnote = existing_footnote.rstrip()

            # Build new footnote value with the trailing ref appended
            new_footnote_value = existing_footnote + trailing_refs.strip()

            # Replace the footnote parameter in the template
            new_template = (
                template[:footnote_match.start()] +
                prefix + new_footnote_value + suffix +
                template[footnote_match.end():]
            )
            changes += 1
            return new_template
        else:
            # No footnote parameter found - this shouldn't happen in practice
            # but if it does, we'll just leave it as is
            return match.group(0)

    # Keep replacing until no more matches
    prev_wikitext = None
    while prev_wikitext != wikitext:
        prev_wikitext = wikitext
        wikitext = template_pattern.sub(replace_template, wikitext)

    return wikitext, changes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Move refs from after census table into footnote parameter."
    )
    parser.add_argument(
        "--state-postal",
        required=True,
        help="State postal code(s), comma-separated (e.g., TN or OK,TX).",
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
        default="Move census table refs into footnote parameter",
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

    state_postals = _split_state_postals(args.state_postal)
    for state_postal in state_postals:
        try:
            titles = load_municipality_titles(state_postal, args.municipality_type)
        except FileNotFoundError as exc:
            errors += 1
            print(f"Error: {exc}")
            continue
        for name in titles:
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
                new_text, count = move_census_refs_to_footnote(wikitext)
                if count == 0:
                    print(f"No change: {title}")
                else:
                    if args.apply:
                        result = client.edit_article_wikitext(
                            title, new_text, summary=args.summary
                        )
                        if result.get("edit", {}).get("result") == "Success":
                            updated += 1
                            print(f"Updated: {title} ({count} ref(s) moved)")
                        else:
                            errors += 1
                            print(f"Edit failed: {title} -> {result}")
                    else:
                        updated += 1
                        print(f"Would update: {title} ({count} ref(s) moved)")
            except Exception as exc:
                errors += 1
                print(f"Error: {name} -> {exc}")

            time.sleep(args.sleep)

        if args.limit and total > args.limit:
            break

    mode = "apply" if args.apply else "dry-run"
    print(
        f"Done ({mode}). Total processed: {total}. "
        f"Updated: {updated}. Errors: {errors}."
    )


if __name__ == "__main__":
    main()
