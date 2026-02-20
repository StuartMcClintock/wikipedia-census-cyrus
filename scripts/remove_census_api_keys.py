#!/usr/bin/env python3
"""
Remove Census API keys from Wikipedia articles for counties or municipalities.

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
from census_api.utils import strip_census_key

WIKIPEDIA_ENDPOINT = "https://en.wikipedia.org/w/api.php"
FIPS_MAPPING_DIR = ROOT_DIR / "census_api" / "fips_mappings"
STATE_TO_FIPS_PATH = FIPS_MAPPING_DIR / "state_to_fips.json"
COUNTY_FIPS_DIR = FIPS_MAPPING_DIR / "county_to_fips"
MUNICIPALITY_FIPS_DIR = FIPS_MAPPING_DIR / "municipality_to_fips"
NON_STATE_POSTALS = {"AS", "GU", "MP", "PR", "VI"}

CENSUS_URL_RE = re.compile(
    r"https?://api\.census\.gov[^\s<>\]\|}]+",
    flags=re.IGNORECASE,
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


def _strip_key_from_url(url: str) -> str:
    normalized = url.replace("&amp;", "&")
    stripped = strip_census_key(normalized)
    if "&amp;" in url and "&" in stripped:
        stripped = stripped.replace("&", "&amp;")
    return stripped


def remove_census_api_keys(wikitext: str) -> Tuple[str, int]:
    changes = 0

    def replacer(match: re.Match) -> str:
        nonlocal changes
        url = match.group(0)
        if "key=" not in url.lower():
            return url
        cleaned = _strip_key_from_url(url)
        if cleaned != url:
            changes += 1
        return cleaned

    updated = CENSUS_URL_RE.sub(replacer, wikitext)
    return updated, changes


def process_article(
    article_title: str,
    client: WikipediaClient,
    is_county: bool,
    apply_changes: bool,
    summary: str,
) -> Tuple[bool, Optional[str]]:
    title, wikitext = client.fetch_article_wikitext(article_title)
    if wikitext.lstrip().lower().startswith("#redirect"):
        return False, f"Skipping '{title}' because it is a redirect."

    updated_text, count = remove_census_api_keys(wikitext)
    if count == 0:
        return False, f"No change: {title}"

    if apply_changes:
        result = client.edit_article_wikitext(title, updated_text, summary=summary)
        if result.get("edit", {}).get("result") == "Success":
            return True, f"Updated: {title} (removed {count} key(s))"
        return False, f"Edit failed: {title} -> {result}"
    return True, f"Would update: {title} (removed {count} key(s))"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove Census API keys from Wikipedia articles."
    )
    parser.add_argument(
        "--state-postal",
        required=True,
        help="State postal code(s), comma-separated (e.g., OK, OK,TX, or ALL).",
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
        default="Remove Census API keys from citations",
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
    for state_postal in state_postals:
        try:
            if args.counties:
                items = list(load_county_items(state_postal))
                is_county = True
            else:
                items = list(load_municipality_items(state_postal, args.municipality_type))
                is_county = False
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
                    is_county=is_county,
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
