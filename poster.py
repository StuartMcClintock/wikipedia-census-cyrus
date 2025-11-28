import argparse
import json
import os
from pathlib import Path
from typing import Tuple
import requests
from pprint import pprint
from credentials import *  # WP_BOT_USER_NAME, WP_BOT_PASSWORD, WP_BOT_USER_AGENT, USER_SANDBOX_ARTICLE
from county.generate_county_paragraphs import generate_county_paragraphs
from llm_backends.openai_codex.openai_codex import (
    check_if_update_needed,
    update_demographics_section,
    update_wp_page,
)
from parser import ParsedWikitext

BASE_DIR = Path(__file__).resolve().parent
WIKIPEDIA_ENDPOINT = "https://en.wikipedia.org/w/api.php"
FIPS_MAPPING_DIR = BASE_DIR / "census_api" / "fips_mappings"
STATE_TO_FIPS_PATH = FIPS_MAPPING_DIR / "state_to_fips.json"
COUNTY_FIPS_DIR = FIPS_MAPPING_DIR / "county_to_fips"
STATE_FIPS_TO_POSTAL = {
    code.split(":")[1]: postal
    for postal, code in json.loads(STATE_TO_FIPS_PATH.read_text()).items()
}
STATE_NAME_TO_POSTAL = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
    "district of columbia": "DC",
}
_US_LOCATION_SUFFIXES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa",
    "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan",
    "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire",
    "new jersey", "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington", "west virginia",
    "wisconsin", "wyoming", "district of columbia"
}

_SECTION_SENTINELS = {"__lead__", "__content__"}


def find_demographics_section(parsed_article: ParsedWikitext):
    """
    Locate the demographics H2 section and return (index, entry) or None.
    """
    for index, entry in enumerate(parsed_article.sections):
        heading = entry[0]
        if heading in _SECTION_SENTINELS:
            continue
        if heading == "Demographics":
            return index, entry
    return None


def demographics_section_to_wikitext(section_entry):
    """
    Render a demographics section tuple back to raw wikitext.
    """
    temp = ParsedWikitext(sections=[section_entry])
    return temp.to_wikitext()


def _extract_single_section(section_wikitext: str):
    parsed = ParsedWikitext(wikitext=section_wikitext)
    for entry in parsed.sections:
        heading = entry[0]
        if heading in _SECTION_SENTINELS:
            continue
        return entry
    raise ValueError("Updated demographics text did not include a section heading.")


def apply_demographics_section_override(
    parsed_article: ParsedWikitext, section_index: int, updated_section_text: str
) -> ParsedWikitext:
    """
    Return a clone of parsed_article with the demographics section replaced.
    """
    replacement_entry = _extract_single_section(updated_section_text)
    updated_article = parsed_article.clone()
    updated_article.sections[section_index] = replacement_entry
    return updated_article


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Update a county article with 2020 census demographics."
    )
    parser.add_argument(
        "--location",
        help="Human-readable location, e.g., 'Coal County, Oklahoma'.",
    )
    parser.add_argument(
        "--state-fips",
        help="Two-digit state FIPS code (e.g., 40 for Oklahoma).",
    )
    parser.add_argument(
        "--county-fips",
        help="Three-digit county FIPS code (e.g., 029 for Coal County).",
    )
    parser.add_argument(
        "--article",
        help="Explicit Wikipedia article title (optional when --location is provided).",
    )
    parser.add_argument(
        "--skip-location-parsing",
        action="store_true",
        help=(
            "Skip deriving article and FIPS codes from --location. Requires "
            "explicit --article, --state-fips, and --county-fips values."
        ),
    )
    parser.add_argument(
        "--codex-model",
        choices=["gpt-5.1-codex-mini", "gpt-5.1-codex-max"],
        help="Override the Codex model (default: gpt-5.1-codex-mini).",
    )
    args = parser.parse_args()
    has_manual_inputs = args.article and args.state_fips and args.county_fips
    if not args.location and not has_manual_inputs:
        parser.error(
            "Either provide --location or specify --article, --state-fips, and --county-fips."
        )
    if args.skip_location_parsing and not has_manual_inputs:
        parser.error(
            "--skip-location-parsing requires --article, --state-fips, and --county-fips."
        )
    return args


def validate_fips_inputs(state_fips: str, county_fips: str) -> Tuple[str, str]:
    state_code = state_fips.zfill(2)
    county_code = county_fips.zfill(3)
    postal = STATE_FIPS_TO_POSTAL.get(state_code)
    if not postal:
        raise ValueError(f"Unknown state FIPS code '{state_fips}'.")
    county_file = COUNTY_FIPS_DIR / f"{postal}.json"
    if not county_file.exists():
        raise ValueError(f"No county mapping found for state '{postal}'.")

    county_map = json.loads(county_file.read_text())
    expected = f"county:{state_code}{county_code}"
    if expected not in county_map.values():
        raise ValueError(
            f"County FIPS '{county_fips}' does not belong to state '{postal}'."
        )
    return state_code, county_code


def derive_inputs_from_location(location: str) -> Tuple[str, str, str]:
    cleaned = " ".join(location.strip().split())
    if "," not in cleaned:
        raise ValueError("Location must be in the form 'County Name, State Name'.")
    county_part, state_part = [part.strip() for part in cleaned.split(",", 1)]
    state_lower = state_part.lower()
    postal = STATE_NAME_TO_POSTAL.get(state_lower)
    if not postal:
        raise ValueError(f"Unknown state name '{state_part}'.")

    county_file = COUNTY_FIPS_DIR / f"{postal}.json"
    if not county_file.exists():
        raise ValueError(f"No county mapping found for state '{postal}'.")

    county_map = json.loads(county_file.read_text())
    canonical_key = None
    fips_code = None
    target = f"{county_part}, {state_part}".lower()
    for name, code in county_map.items():
        if name.lower() == target:
            canonical_key = name
            fips_code = code.split(":")[1]
            break
    if not fips_code:
        raise ValueError(f"County '{county_part}' not found in state '{state_part}'.")

    state_fips = fips_code[:2]
    county_fips = fips_code[2:]
    article_title = canonical_key.replace(" ", "_")
    return article_title, state_fips, county_fips


def ensure_us_location_title(title):
    """
    Raise a ValueError unless the article title ends with a US state/region name.

    All logic and data needed for this heuristic lives inside this function so it
    can be removed or replaced without touching the WikipediaClient.
    """
    last_segment = title.replace('_', ' ').split(',')[-1].strip().lower()
    if last_segment not in _US_LOCATION_SUFFIXES:
        raise ValueError(
            f"Refusing to edit '{title}' because it does not look like a US location title."
        )


class WikipediaClient:
    """
    Thin wrapper around the Wikipedia API that handles login, tokens, and edits.
    """

    def __init__(self, user_agent):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self._csrf_token = None

    def _get(self, params):
        response = self.session.get(WIKIPEDIA_ENDPOINT, params=params)
        response.raise_for_status()
        return response

    def _post(self, data):
        response = self.session.post(WIKIPEDIA_ENDPOINT, data=data)
        response.raise_for_status()
        return response

    def get_login_token(self):
        params = {
            'action': 'query',
            'meta': 'tokens',
            'type': 'login',
            'format': 'json'
        }
        response = self._get(params)
        return response.json()['query']['tokens']['logintoken']

    def login(self, username, password):
        login_token = self.get_login_token()
        payload = {
            'action': 'login',
            'lgname': username,
            'lgpassword': password,
            'lgtoken': login_token,
            'format': 'json'
        }
        response = self._post(payload)
        data = response.json()
        if data['login']['result'] != 'Success':
            raise Exception(f"Login failed: {data['login']['result']}")
        print(f"Successfully logged in as {username}")
        return data

    def get_csrf_token(self):
        if self._csrf_token:
            return self._csrf_token
        params = {
            'action': 'query',
            'meta': 'tokens',
            'type': 'csrf',
            'format': 'json'
        }
        response = self._get(params)
        self._csrf_token = response.json()['query']['tokens']['csrftoken']
        return self._csrf_token

    def fetch_article_wikitext(self, title):
        params = {
            'action': 'query',
            'prop': 'revisions',
            'titles': title,
            'rvprop': 'content',
            'rvslots': 'main',
            'formatversion': '2',
            'format': 'json'
        }
        response = self._get(params)
        data = response.json()
        pages = data.get('query', {}).get('pages', [])
        if not pages:
            raise ValueError(f"Wikipedia API returned no page data for '{title}'.")

        page = pages[0]
        if 'missing' in page:
            raise ValueError(f"Wikipedia article '{title}' does not exist.")
        if 'invalidreason' in page:
            raise ValueError(f"Invalid article title '{title}': {page['invalidreason']}.")
        if 'revisions' not in page:
            raise ValueError(
                f"Wikipedia API response for '{title}' is missing revisions data: {page}."
            )
        return page['revisions'][0]['slots']['main']['content']

    def edit_article_wikitext(self, title, new_text, summary):
        token = self.get_csrf_token()
        payload = {
            'action': 'edit',
            'title': title,
            'text': new_text,
            'summary': summary,
            'token': token,
            'format': 'json',
            'assert': 'user',
            'maxlag': '5'
        }
        response = self._post(payload)
        return response.json()

    def compare_revision_sizes(self, old_revision_id, new_revision_id):
        """
        Fetch the byte sizes of two revisions and return a delta (new - old).
        """
        params = {
            'action': 'compare',
            'fromrev': old_revision_id,
            'torev': new_revision_id,
            'prop': 'size',
            'format': 'json',
        }
        response = self._get(params)
        data = response.json().get('compare', {})
        old_size = data.get('fromsize')
        new_size = data.get('tosize')
        if old_size is None or new_size is None:
            raise ValueError("Revision size information is unavailable.")
        return new_size - old_size

    def edit_article_with_size_check(
        self,
        title,
        parsed_wikitext,
        summary,
        tolerance=2,
        new_text=None,
    ):
        """
        Edit a page and verify the observed size delta roughly matches expectations.
        """
        ensure_us_location_title(title)
        new_text = new_text if new_text is not None else parsed_wikitext.to_wikitext()
        expected_delta = len(new_text) - parsed_wikitext.original_length
        response = self.edit_article_wikitext(title, new_text, summary)
        edit_info = response.get('edit', {})
        old_rev = edit_info.get('oldrevid')
        new_rev = edit_info.get('newrevid')
        if old_rev is not None and new_rev is not None:
            actual_delta = self.compare_revision_sizes(old_rev, new_rev)
            if abs(actual_delta - expected_delta) > tolerance:
                raise ValueError(
                    f"Revision size delta {actual_delta} differs from expected {expected_delta} by more than {tolerance}."
                )
        return response


def main():
    args = parse_arguments()
    if args.codex_model:
        os.environ["CODEX_MODEL"] = args.codex_model

    if args.location and not args.skip_location_parsing:
        try:
            article_title, state_fips, county_fips = derive_inputs_from_location(args.location)
        except ValueError as exc:
            print(f"Location parsing failed: {exc}")
            return
    else:
        try:
            state_fips, county_fips = validate_fips_inputs(
                args.state_fips,
                args.county_fips,
            )
        except ValueError as exc:
            print(f"FIPS validation failed: {exc}")
            return
        article_title = args.article.replace(" ", "_")
    ensure_us_location_title(article_title)

    client = WikipediaClient(WP_BOT_USER_AGENT)
    client.login(WP_BOT_USER_NAME, WP_BOT_PASSWORD)

    page_wikitext = client.fetch_article_wikitext(article_title)
    parsed_article = ParsedWikitext(wikitext=page_wikitext)
    demographics_section_info = find_demographics_section(parsed_article)
    proposed_text = generate_county_paragraphs(state_fips, county_fips)
    print(proposed_text)

    if not check_if_update_needed(page_wikitext, proposed_text):
        print("No updates are necessary; skipping edit.")
        return

    updated_article = None
    if demographics_section_info:
        section_index, section_entry = demographics_section_info
        current_demographics = demographics_section_to_wikitext(section_entry)
        try:
            new_demographics_section = update_demographics_section(
                current_demographics,
                proposed_text,
            )
            updated_parsed_article = apply_demographics_section_override(
                parsed_article,
                section_index,
                new_demographics_section,
            )
            updated_article = updated_parsed_article.to_wikitext()
        except Exception as exc:
            print(
                f"Demographics-only update failed ({exc}); falling back to full article update."
            )
    if updated_article is None:
        updated_article = update_wp_page(page_wikitext, proposed_text)
    result = client.edit_article_wikitext(
        article_title,
        updated_article,
        "Add 2020 census data",
    )
    pprint(result)


if __name__ == '__main__':
    main()
