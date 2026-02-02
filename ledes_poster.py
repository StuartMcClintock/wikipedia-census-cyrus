import argparse
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Dict, Iterable, Optional, Set, Tuple
from pprint import pprint

import requests

from app_logging.logger import LOG_DIR, log_edit_article
from census_api.constants import PL_ENDPOINT, CITATION_DETAILS
from credentials import *  # WP_BOT_USER_NAME, WP_BOT_PASSWORD, WP_BOT_USER_AGENT
from llm_frontend import update_lede
from municipality.lede_classifier import classify_lede
from municipality.muni_type_classifier import determine_municipality_type
from parser.parser import ParsedWikitext
from constants import DEFAULT_CODEX_MODEL, get_all_model_options

BASE_DIR = Path(__file__).resolve().parent
WIKIPEDIA_ENDPOINT = "https://en.wikipedia.org/w/api.php"
FIPS_MAPPING_DIR = BASE_DIR / "census_api" / "fips_mappings"
STATE_TO_FIPS_PATH = FIPS_MAPPING_DIR / "state_to_fips.json"
MUNICIPALITY_FIPS_DIR = FIPS_MAPPING_DIR / "municipality_to_fips"
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
LEDE_LOG_FILE = LOG_DIR / "lede_edits.log"
today = datetime.date.today()
ACCESS_DATE = f"{today.strftime('%B')} {today.day}, {today.year}"
DIFF_LOG_PATH = BASE_DIR / "diffs_to_check.txt"
_SUCCESS_RESULT_KEY = "Success"


def _load_successful_articles(log_path: Path = LEDE_LOG_FILE) -> Set[str]:
    """
    Read lede edit log and return a set of article titles that logged a successful edit.
    """
    successes: Set[str] = set()
    try:
        if not log_path.exists():
            return successes
        with log_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                result = entry.get("result", {})
                edit = result.get("edit") if isinstance(result, dict) else None
                if not isinstance(edit, dict):
                    continue
                if edit.get("result") == "Success":
                    article = entry.get("article") or edit.get("title")
                    if article:
                        successes.add(article)
    except Exception:
        return successes
    return successes


def _normalize_location_key(value: str) -> str:
    return " ".join(value.strip().split()).lower()


def derive_inputs_from_municipality(location: str) -> Tuple[str, str, str]:
    cleaned = " ".join(location.strip().split())
    if "," not in cleaned:
        raise ValueError("Location must be in the form 'Place Name, State Name'.")
    place_part, state_part = [part.strip() for part in cleaned.split(",", 1)]
    state_lower = state_part.lower()
    postal = STATE_NAME_TO_POSTAL.get(state_lower)
    if not postal:
        raise ValueError(f"Unknown state name '{state_part}'.")
    state_dir = MUNICIPALITY_FIPS_DIR / postal
    if not state_dir.exists():
        raise ValueError(f"No municipality mapping found for state '{postal}'.")

    target = _normalize_location_key(f"{place_part}, {state_part}")
    for type_dir in state_dir.iterdir():
        if not type_dir.is_dir():
            continue
        path = type_dir / "places.json"
        if not path.exists():
            continue
        mapping = json.loads(path.read_text())
        for name, codes in mapping.items():
            if _normalize_location_key(name) != target:
                continue
            state_code = str(codes.get("state", "")).zfill(2)
            place_code = str(codes.get("place", "")).zfill(5)
            if not state_code or not place_code:
                break
            article_title = name.replace(" ", "_")
            return article_title, state_code, place_code
    raise ValueError(f"Municipality '{place_part}' not found in state '{state_part}'.")


def validate_place_inputs(state_fips: str, place_fips: str) -> Tuple[str, str]:
    state_code = state_fips.zfill(2)
    place_code = place_fips.zfill(5)
    postal = STATE_FIPS_TO_POSTAL.get(state_code)
    if not postal:
        raise ValueError(f"Unknown state FIPS code '{state_fips}'.")
    state_dir = MUNICIPALITY_FIPS_DIR / postal
    if not state_dir.exists():
        raise ValueError(f"No municipality mapping found for state '{postal}'.")
    for type_dir in state_dir.iterdir():
        if not type_dir.is_dir():
            continue
        path = type_dir / "places.json"
        if not path.exists():
            continue
        mapping = json.loads(path.read_text())
        for codes in mapping.values():
            mapped_state = str(codes.get("state", "")).zfill(2)
            mapped_place = str(codes.get("place", "")).zfill(5)
            if mapped_state == state_code and mapped_place == place_code:
                return state_code, place_code
    raise ValueError(
        f"Place FIPS '{place_fips}' does not belong to state '{postal}'."
    )


def ensure_us_location_title(title):
    """
    Raise a ValueError unless the article title ends with a US state/region name.
    """
    last_segment = title.replace('_', ' ').split(',')[-1].strip().lower()
    if last_segment not in _US_LOCATION_SUFFIXES:
        raise ValueError(
            f"Refusing to edit '{title}' because it does not look like a US location title."
        )


def _resolve_municipality_type_dir(
    state_dir: Path, municipality_type: str
) -> Optional[Path]:
    normalized = municipality_type.strip().lower()
    for entry in state_dir.iterdir():
        if entry.is_dir() and entry.name.lower() == normalized:
            return entry
    return None


class WikipediaClient:
    """
    Thin wrapper around the Wikipedia API that handles login, tokens, and edits.
    """

    def __init__(self, user_agent, log_file: Path = LEDE_LOG_FILE):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self._csrf_token = None
        self.log_file = log_file

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

    def fetch_article_lede_text(self, title):
        params = {
            'action': 'query',
            'prop': 'extracts',
            'titles': title,
            'redirects': 1,
            'exintro': 1,
            'explaintext': 1,
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
        return page.get('extract', '') or ''

    def is_disambiguation_page(self, title):
        params = {
            'action': 'query',
            'format': 'json',
            'redirects': 1,
            'titles': title,
            'prop': 'pageprops',
            'ppprop': 'disambiguation',
        }
        response = self._get(params)
        data = response.json()
        pages = data.get('query', {}).get('pages', {})
        if not pages:
            raise ValueError(f"Wikipedia API returned no page data for '{title}'.")
        page = next(iter(pages.values()))
        if 'missing' in page:
            raise ValueError(f"Wikipedia article '{title}' does not exist.")
        if 'invalidreason' in page:
            raise ValueError(f"Invalid article title '{title}': {page['invalidreason']}.")
        return 'disambiguation' in (page.get('pageprops') or {})

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
            'maxlag': '5',
        }
        response = self._post(payload)
        result = response.json()
        log_edit_article(title, result, log_path=self.log_file)
        return result


def _extract_lede_wikitext(parsed_article: ParsedWikitext) -> str:
    for heading, content in parsed_article.sections:
        if heading == "__lead__":
            return content or ""
    return ""


def _replace_lede_in_article(article_wikitext: str, updated_lede: str) -> str:
    parsed_article = ParsedWikitext(wikitext=article_wikitext)
    for index, entry in enumerate(parsed_article.sections):
        if entry[0] == "__lead__":
            parsed_article.sections[index] = (entry[0], updated_lede)
            break
    return parsed_article.to_wikitext()


def _fetch_place_population(state_fips: str, place_fips: str) -> Tuple[str, int, str]:
    state = state_fips.zfill(2)
    place = place_fips.zfill(5)
    params = {
        "get": "NAME,P1_001N",
        "for": f"place:{place}",
        "in": f"state:{state}",
    }
    response = requests.get(PL_ENDPOINT, params=params)
    response.raise_for_status()
    payload = response.json()
    if not payload or len(payload) < 2:
        raise ValueError("Census API returned no population rows.")
    header = payload[0]
    row = payload[1]
    record = dict(zip(header, row))
    name = record.get("NAME") or ""
    try:
        population = int(record.get("P1_001N"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Census API returned an invalid population value.") from exc
    return name, population, response.url


def _build_population_sentence(display_title: str, population: int, census_url: str) -> str:
    if "," in display_title:
        base, suffix = display_title.rsplit(",", 1)
        if suffix.strip().lower() in _US_LOCATION_SUFFIXES:
            display_title = base.strip()
    ref = _build_lede_census_ref(census_url)
    return (
        f"As of the [[2020 United States census|2020 census]], {display_title} had a population of "
        f"{population:,}.{ref}"
    )


def _ensure_template_closed(template: str) -> str:
    trimmed = template.strip()
    while trimmed.startswith("{"):
        trimmed = trimmed[1:]
    while trimmed.endswith("}"):
        trimmed = trimmed[:-1]
    return "{{" + trimmed.strip() + "}}"


def _build_lede_census_ref(census_url: str) -> str:
    detail = CITATION_DETAILS["pl"]
    template = detail["template"].format(url=census_url, access_date=ACCESS_DATE)
    return f'<ref name="Census2020PLLede">{_ensure_template_closed(template)}</ref>'


def _print_type_mismatch(article_title: str, expected_type: str, detected: Dict[str, object]) -> None:
    detected_type = (detected.get("type") or "unknown").strip()
    reasons = detected.get("reasons") or []
    reason_text = "; ".join(reasons) if reasons else "no reasons provided"
    print(
        "\n\n\n"
        "MUNICIPALITY TYPE MISMATCH - SKIPPING ARTICLE\n"
        f"Article: {article_title.replace('_', ' ')}\n"
        f"Expected type: {expected_type}\n"
        f"Detected type: {detected_type}\n"
        f"Classifier reasons: {reason_text}\n"
        "\n\n\n"
    )


def _append_diff_link(article_title: str, edit_response: dict) -> None:
    """
    Append a diff URL for a successful edit to diffs_to_check.txt.
    """
    try:
        edit = edit_response.get("edit", {})
        if edit.get("result") != _SUCCESS_RESULT_KEY:
            return
        old_rev = edit.get("oldrevid")
        new_rev = edit.get("newrevid")
        if not old_rev or not new_rev:
            return
        title = (edit.get("title") or article_title).replace(" ", "_")
        diff_url = (
            f"https://en.wikipedia.org/w/index.php?title={title}&diff={new_rev}&oldid={old_rev}"
        )
        DIFF_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DIFF_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(diff_url + "\n")
    except Exception:
        # Never let diff logging break the main flow.
        pass


def process_single_article(
    article_title: str,
    state_fips: str,
    place_fips: str,
    args,
    client,
    expected_muni_type: Optional[str] = None,
):
    display_title = article_title.replace("_", " ")
    ensure_us_location_title(article_title)
    if client.is_disambiguation_page(article_title):
        print(
            f"Skipping '{display_title}' because it is a disambiguation page."
        )
        return
    page_wikitext = client.fetch_article_wikitext(article_title)
    if page_wikitext.lstrip().lower().startswith("#redirect"):
        print(f"Skipping '{display_title}' because it is a redirect.")
        return
    if expected_muni_type:
        detected = determine_municipality_type(page_wikitext)
        if detected.get("type", "").lower().strip() != expected_muni_type.lower().strip():
            _print_type_mismatch(article_title, expected_muni_type, detected)
            return

    lede_plain_text = client.fetch_article_lede_text(article_title)
    decision = classify_lede(lede_plain_text)
    if decision == "SKIP":
        print(f"Skipping '{display_title}' (lede already contains a 2020+ population).")
        return

    current_lede = _extract_lede_wikitext(ParsedWikitext(wikitext=page_wikitext))
    if not current_lede.strip():
        print(f"Skipping '{display_title}' because no lede text was found.")
        return

    _, population, census_url = _fetch_place_population(state_fips, place_fips)
    population_sentence = _build_population_sentence(display_title, population, census_url)

    suppress_out = not args.show_codex_output
    updated_lede = update_lede(current_lede, population_sentence, suppress_out=suppress_out)
    if not updated_lede or not updated_lede.strip():
        print(f"Skipping '{display_title}' because the LLM returned no content.")
        return
    if updated_lede.strip() == current_lede.strip():
        print(f"No lede updates needed for '{display_title}'.")
        return

    updated_article = _replace_lede_in_article(page_wikitext, updated_lede)
    result = client.edit_article_wikitext(
        article_title,
        updated_article,
        "Update 2020 census population in lede",
    )
    _append_diff_link(article_title, result)
    pprint(result)


def process_single_article_with_retries(
    article_title: str,
    state_fips: str,
    place_fips: str,
    args,
    client,
    skip_successful_articles: Iterable[str] = None,
    expected_muni_type: Optional[str] = None,
):
    if skip_successful_articles and article_title in skip_successful_articles:
        print(
            f"Skipping '{article_title.replace('_', ' ')}' (already logged as a successful edit)."
        )
        return
    try:
        process_single_article(
            article_title,
            state_fips,
            place_fips,
            args,
            client,
            expected_muni_type=expected_muni_type,
        )
    except Exception as exc:
        display_title = article_title.replace("_", " ")
        print(f"Failed to update '{display_title}': {exc}")


def process_municipality_batch(
    state_postal: str,
    municipality_type: str,
    client,
    args,
    start_muni_fips: str = None,
    skip_successful_articles: Iterable[str] = None,
):
    postal = state_postal.strip().upper()
    state_dir = MUNICIPALITY_FIPS_DIR / postal
    if not state_dir.exists():
        print(f"No municipality mapping found for state '{postal}'.")
        return
    type_dir = _resolve_municipality_type_dir(state_dir, municipality_type)
    if not type_dir:
        available = sorted(
            entry.name for entry in state_dir.iterdir() if entry.is_dir()
        )
        print(
            f"No municipality type '{municipality_type}' found for state '{postal}'."
        )
        if available:
            print("Available types: " + ", ".join(available))
        return
    path = type_dir / "places.json"
    if not path.exists():
        print(
            f"No municipality mapping found for state '{postal}' and type '{type_dir.name}'."
        )
        return
    place_map = json.loads(path.read_text())
    start_threshold = start_muni_fips.zfill(5) if start_muni_fips else None

    def _place_sort_key(item):
        name, codes = item
        raw_place = codes.get("place") if isinstance(codes, dict) else None
        if raw_place is None:
            return ("99999", name.lower())
        return (str(raw_place).zfill(5), name.lower())

    if start_threshold:
        items = sorted(place_map.items(), key=_place_sort_key)
    else:
        items = sorted(place_map.items(), key=lambda kv: kv[0].lower())

    for article_title, codes in items:
        try:
            raw_state = codes.get("state")
            raw_place = codes.get("place")
            if raw_state is None or raw_place is None:
                raise ValueError("Missing state or place code in mapping.")
            state_fips = str(raw_state).zfill(2)
            place_fips = str(raw_place).zfill(5)
            if start_threshold and place_fips < start_threshold:
                continue
            process_single_article_with_retries(
                article_title.replace(" ", "_"),
                state_fips,
                place_fips,
                args,
                client,
                skip_successful_articles=skip_successful_articles,
                expected_muni_type=type_dir.name,
            )
        except Exception as exc:
            print(f"Failed to update '{article_title}': {exc}")


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Update a municipality lede with 2020 census population."
    )
    parser.add_argument(
        "--state-postal",
        help=(
            "Process all municipalities in a state by postal code (e.g., OK). "
            "Requires --municipality-type."
        ),
    )
    parser.add_argument(
        "--municipality-type",
        help=(
            "When used with --state-postal, process all municipalities of this type "
            "(e.g., city, town, CDP). Quote multi-word types like 'city and borough'."
        ),
    )
    parser.add_argument(
        "--municipality",
        help="Human-readable municipality, e.g., 'Oktaha, Oklahoma'.",
    )
    parser.add_argument(
        "--state-fips",
        help="Two-digit state FIPS code (e.g., 40 for Oklahoma).",
    )
    parser.add_argument(
        "--place-fips",
        help="Five-digit place FIPS code (e.g., 55150 for Oktaha).",
    )
    parser.add_argument(
        "--article",
        help="Explicit Wikipedia article title (required with --place-fips).",
    )
    parser.add_argument(
        "--model",
        choices=get_all_model_options(),
        help="Override the model (default: gpt-5.1-codex-max).",
    )
    parser.add_argument(
        "--start-muni-fips",
        help=(
            "When used with --state-postal and --municipality-type, start processing at "
            "this 5-digit place FIPS code and continue upward (e.g., 31050)."
        ),
    )
    parser.add_argument(
        "--skip-logged-successes",
        action="store_true",
        help="Skip updating articles already logged as successful edits in app_logging/logs/lede_edits.log.",
    )
    parser.add_argument(
        "--show-codex-output",
        action="store_true",
        help="Display LLM output to stdout instead of suppressing it.",
    )
    args = parser.parse_args()

    if args.municipality and args.place_fips:
        parser.error("--municipality cannot be combined with --place-fips.")
    if args.place_fips and not (args.article and args.state_fips):
        parser.error("--place-fips requires --article and --state-fips.")
    if args.state_postal and (args.article or args.municipality):
        parser.error("--state-postal cannot be combined with --article or --municipality.")
    if args.municipality_type and not args.state_postal:
        parser.error("--municipality-type can only be used with --state-postal.")
    if args.start_muni_fips and not args.state_postal:
        parser.error("--start-muni-fips can only be used with --state-postal.")
    if args.start_muni_fips and not args.municipality_type:
        parser.error("--start-muni-fips requires --municipality-type.")
    if args.start_muni_fips:
        if not args.start_muni_fips.isdigit():
            parser.error("--start-muni-fips must be numeric (e.g., 31050).")
        if len(args.start_muni_fips) > 5:
            parser.error("--start-muni-fips must be a 5-digit place code.")
    if not args.municipality and not args.place_fips and not args.state_postal:
        parser.error(
            "Provide --municipality, --state-postal with --municipality-type, or specify --article, --state-fips, and --place-fips."
        )
    return args


def main():
    args = parse_arguments()
    if args.model:
        os.environ["ACTIVE_MODEL"] = args.model

    skip_successful_articles = (
        _load_successful_articles() if args.skip_logged_successes else set()
    )

    client = WikipediaClient(WP_BOT_USER_AGENT, log_file=LEDE_LOG_FILE)
    client.login(WP_BOT_USER_NAME, WP_BOT_PASSWORD)

    try:
        if args.state_postal:
            process_municipality_batch(
                args.state_postal,
                args.municipality_type,
                client,
                args,
                start_muni_fips=args.start_muni_fips,
                skip_successful_articles=skip_successful_articles,
            )
            return

        if args.municipality:
            try:
                article_title, state_fips, place_fips = derive_inputs_from_municipality(
                    args.municipality
                )
            except ValueError as exc:
                print(f"Municipality parsing failed: {exc}")
                return
        else:
            try:
                state_fips, place_fips = validate_place_inputs(
                    args.state_fips,
                    args.place_fips,
                )
            except ValueError as exc:
                print(f"FIPS validation failed: {exc}")
                return
            article_title = args.article.replace(" ", "_")

        process_single_article_with_retries(
            article_title,
            state_fips,
            place_fips,
            args,
            client,
            skip_successful_articles=skip_successful_articles,
        )
    except Exception as exc:
        print(f"Failed to update: {exc}")


if __name__ == "__main__":
    main()
