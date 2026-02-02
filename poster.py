import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Iterable, Optional, Set, Tuple
import requests
from pprint import pprint
from census_api.fetch_county_data import CensusFetchError
from credentials import *  # WP_BOT_USER_NAME, WP_BOT_PASSWORD, WP_BOT_USER_AGENT, USER_SANDBOX_ARTICLE
from county.generate_county_paragraphs import generate_county_paragraphs
from municipality.generate_municipality_paragraphs import generate_municipality_paragraphs
from municipality.muni_type_classifier import determine_municipality_type
from app_logging.logger import LOG_FILE, log_edit_article
from llm_frontend import (
    check_if_update_needed,
    update_demographics_section,
    update_wp_page,
)
from llm_backends.openai_codex.openai_codex import (
    CodexOutputMissingError,
    CodexUsageLimitError,
)
from constants import DEFAULT_CODEX_MODEL, DEFAULT_ANTHROPIC_MODEL
from parser.parser import ParsedWikitext, fix_demographics_section_in_article
from constants import get_all_model_options

BASE_DIR = Path(__file__).resolve().parent
WIKIPEDIA_ENDPOINT = "https://en.wikipedia.org/w/api.php"
FIPS_MAPPING_DIR = BASE_DIR / "census_api" / "fips_mappings"
STATE_TO_FIPS_PATH = FIPS_MAPPING_DIR / "state_to_fips.json"
COUNTY_FIPS_DIR = FIPS_MAPPING_DIR / "county_to_fips"
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

_SECTION_SENTINELS = {"__lead__", "__content__"}
_DISABLE_RETRY_ENV = "DISABLE_COUNTY_RETRIES"
_SUCCESS_RESULT_KEY = "Success"
DIFF_LOG_PATH = BASE_DIR / "diffs_to_check.txt"


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


def _county_retry_enabled(args) -> bool:
    """
    Return True when automatic retry for county updates is enabled.
    Default is enabled; can be disabled via CLI or env flag.
    """
    env_disabled = os.getenv(_DISABLE_RETRY_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return not env_disabled and not getattr(args, "disable_county_retries", False)


def _load_successful_articles(log_path: Path = LOG_FILE) -> Set[str]:
    """
    Read edit.log and return a set of article titles that logged a successful edit.
    """
    successes: Set[str] = set()
    try:
        if not log_path.exists():
            return successes
        with log_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                    edit = entry.get("result", {}).get("edit", {})
                    if edit.get("result") == _SUCCESS_RESULT_KEY:
                        article = entry.get("article")
                        if article:
                            successes.add(article)
                except Exception:
                    continue
    except Exception:
        pass
    return successes


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
    county_fips: str,
    args,
    client,
    use_mini_prompt: bool,
    location_kind: str = "county",
    expected_muni_type: Optional[str] = None,
):
    display_title = article_title.replace("_", " ")
    ensure_us_location_title(article_title)
    if client.is_disambiguation_page(article_title):
        print(
            f"Skipping '{article_title.replace('_', ' ')}' because it is a disambiguation page."
        )
        return
    page_wikitext = client.fetch_article_wikitext(article_title)
    if page_wikitext.lstrip().lower().startswith("#redirect"):
        print(f"Skipping '{article_title.replace('_', ' ')}' because it is a redirect.")
        return
    if location_kind == "municipality" and expected_muni_type:
        detected = determine_municipality_type(page_wikitext)
        detected_type = (detected.get("type") or "").strip()
        expected_norm = expected_muni_type.strip().lower()
        detected_norm = detected_type.lower()
        if expected_norm != detected_norm:
            reasons = detected.get("reasons") or []
            reason_text = "; ".join(reasons) if reasons else "no reasons provided"
            print(
                "\n\n\n"
                "MUNICIPALITY TYPE MISMATCH - SKIPPING ARTICLE\n"
                f"Article: {article_title.replace('_', ' ')}\n"
                f"Expected type: {expected_muni_type}\n"
                f"Detected type: {detected_type or 'unknown'}\n"
                f"Classifier reasons: {reason_text}\n"
                "\n\n\n"
            )
            return
    parsed_article = ParsedWikitext(wikitext=page_wikitext)
    demographics_section_info = find_demographics_section(parsed_article)
    original_demographics = None
    if location_kind == "municipality":
        proposed_text = generate_municipality_paragraphs(
            state_fips, county_fips, full_first_paragraph_refs=True
        )
    else:
        proposed_text = generate_county_paragraphs(
            state_fips, county_fips, full_first_paragraph_refs=True
        )
    suppress_codex_out = not args.show_codex_output

    should_update = True
    if not args.skip_should_update_check:
        should_update = check_if_update_needed(
            page_wikitext, proposed_text, suppress_out=suppress_codex_out
        )
        if not should_update:
            print(
                "Should-update check: page already contains proposed census text; skipping update."
            )

    if not should_update:
        print(f"No updates are necessary for '{article_title}'; skipping edit.")
        return

    updated_article = None
    if demographics_section_info:
        section_index, section_entry = demographics_section_info
        current_demographics = demographics_section_to_wikitext(section_entry)
        original_demographics = current_demographics
        try:
            new_demographics_section = update_demographics_section(
                current_demographics,
                proposed_text,
                mini=use_mini_prompt,
                suppress_out=suppress_codex_out,
            )
            updated_parsed_article = apply_demographics_section_override(
                parsed_article,
                section_index,
                new_demographics_section,
            )
            updated_article = updated_parsed_article.to_wikitext()
        except CodexOutputMissingError as exc:
            print(
                f"Demographics-only update skipped for '{article_title.replace('_', ' ')}' because Codex output was missing ({exc})."
            )
            return
        except CodexUsageLimitError:
            raise
        except RuntimeError as exc:
            if "response missing content" in str(exc).lower():
                print(
                    f"Demographics-only update skipped for '{display_title}' because the LLM returned no content ({exc})."
                )
                return
            raise
        except ValueError as exc:
            message = str(exc).lower()
            if "section heading" in message:
                print(
                    "\nDemographics-only LLM output lacked a section heading; "
                    "printing raw output and aborting instead of falling back:\n"
                )
                try:
                    print(new_demographics_section)
                except Exception:
                    print("[No demographics section text captured]")
                sys.exit(1)
            raise
        except Exception as exc:
            banner = "!" * 72
            print(
                f"\n{banner}\n"
                f"WARNING: Demographics-only update failed for '{display_title}'.\n"
                f"FALLING BACK to FULL ARTICLE LLM rewrite (other sections may change).\n"
                f"Error: {exc}\n"
                f"{banner}\n"
            )
    if updated_article is None:
        updated_article = update_wp_page(
            page_wikitext, proposed_text, suppress_out=suppress_codex_out
        )

    if not args.skip_deterministic_fixes:
        fix_state_fips = state_fips if location_kind == "county" else None
        fix_county_fips = county_fips if location_kind == "county" else None
        updated_article = fix_demographics_section_in_article(
            updated_article,
            original_demographics_wikitext=original_demographics,
            state_fips=fix_state_fips,
            county_fips=fix_county_fips,
        )
    result = client.edit_article_wikitext(
        article_title,
        updated_article,
        "Add 2020 census data",
    )
    _append_diff_link(article_title, result)
    pprint(result)


def process_single_article_with_retries(
    article_title: str,
    state_fips: str,
    county_fips: str,
    args,
    client,
    use_mini_prompt: bool,
    skip_successful_articles: Iterable[str] = None,
    location_kind: str = "county",
    expected_muni_type: Optional[str] = None,
):
    """
    Attempt to process a county article, retrying up to 3 times by default.
    """
    if skip_successful_articles and article_title in skip_successful_articles:
        print(
            f"Skipping '{article_title.replace('_', ' ')}' (already logged as a successful edit)."
        )
        return
    max_attempts = 3 if _county_retry_enabled(args) else 1
    attempt = 0
    while attempt < max_attempts:
        attempt += 1
        try:
            process_single_article(
                article_title,
                state_fips,
                county_fips,
                args,
                client,
                use_mini_prompt,
                location_kind=location_kind,
                expected_muni_type=expected_muni_type,
            )
            return
        except CodexUsageLimitError:
            raise
        except CensusFetchError as exc:
            display_title = article_title.replace("_", " ")
            if attempt < max_attempts:
                print(
                    f"Attempt {attempt} for '{display_title}' failed due to census fetch error ({exc}); retrying..."
                )
                continue
            print(f"Failed to update '{display_title}' after {attempt} attempts: {exc}")
            return
        except Exception as exc:
            display_title = article_title.replace("_", " ")
            print(
                f"Failed to update '{display_title}' due to non-retriable error: {exc}"
            )
            return


def process_state_batch(
    state_postal: str,
    client,
    args,
    use_mini_prompt: bool,
    start_county_fips: str = None,
    skip_successful_articles: Iterable[str] = None,
):
    postal = state_postal.strip().upper()
    county_file = COUNTY_FIPS_DIR / f"{postal}.json"
    if not county_file.exists():
        print(f"No county mapping found for state '{postal}'.")
        return
    county_map = json.loads(county_file.read_text())
    items = sorted(county_map.items(), key=lambda kv: kv[1])
    start_threshold = start_county_fips.zfill(3) if start_county_fips else None
    for article_title, code in items:
        try:
            if not code.startswith("county:"):
                raise ValueError(f"Unexpected FIPS mapping value '{code}'")
            digits = code.split(":", 1)[1]
            if len(digits) != 5:
                raise ValueError(f"Unexpected FIPS code format '{code}'")
            state_fips = digits[:2]
            county_fips = digits[2:]
            if start_threshold and county_fips < start_threshold:
                continue
            process_single_article_with_retries(
                article_title.replace(" ", "_"),
                state_fips,
                county_fips,
                args,
                client,
                use_mini_prompt,
                skip_successful_articles=skip_successful_articles,
            )
        except CodexUsageLimitError:
            raise
        except Exception as exc:
            print(f"Failed to update '{article_title}': {exc}")


def _resolve_municipality_type_dir(
    state_dir: Path, municipality_type: str
) -> Optional[Path]:
    normalized = municipality_type.strip().lower()
    for entry in state_dir.iterdir():
        if entry.is_dir() and entry.name.lower() == normalized:
            return entry
    return None


def process_municipality_batch(
    state_postal: str,
    municipality_type: str,
    client,
    args,
    use_mini_prompt: bool,
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
                use_mini_prompt,
                skip_successful_articles=skip_successful_articles,
                location_kind="municipality",
                expected_muni_type=type_dir.name,
            )
        except CodexUsageLimitError:
            raise
        except Exception as exc:
            print(f"Failed to update '{article_title}': {exc}")


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Update a county or municipality article with 2020 census demographics."
    )
    parser.add_argument(
        "--state-postal",
        help=(
            "Process all counties in a state by postal code (e.g., OK). "
            "Use with --municipality-type to process municipalities instead."
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
        "--location",
        help="Human-readable location, e.g., 'Coal County, Oklahoma'.",
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
        "--county-fips",
        help="Three-digit county FIPS code (e.g., 029 for Coal County).",
    )
    parser.add_argument(
        "--place-fips",
        help="Five-digit place FIPS code (e.g., 55150 for Oktaha).",
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
        "--model",
        choices=get_all_model_options(),
        help="Override the model (default: gpt-5.1-codex-max).",
    )
    parser.add_argument(
        "--start-county-fips",
        help=(
            "When used with --state-postal, start processing at this 3-digit county FIPS "
            "code and continue upward (e.g., 003)."
        ),
    )
    parser.add_argument(
        "--start-muni-fips",
        help=(
            "When used with --state-postal and --municipality-type, start processing at "
            "this 5-digit place FIPS code and continue upward (e.g., 31050)."
        ),
    )
    parser.add_argument(
        "--skip-should-update-check",
        action="store_true",
        help="Skip the Codex-based update check and always apply the update.",
    )
    parser.add_argument(
        "--skip-deterministic-fixes",
        action="store_true",
        help="Skip deterministic cleanup of the demographics section.",
    )
    parser.add_argument(
        "--show-codex-output",
        action="store_true",
        help="Display Codex output to stdout instead of suppressing it.",
    )
    parser.add_argument(
        "--disable-county-retries",
        action="store_true",
        help=(
            "Disable automatic per-county retry (default: up to 3 attempts per county; "
            f"can also disable via ${_DISABLE_RETRY_ENV})."
        ),
    )
    parser.add_argument(
        "--skip-logged-successes",
        action="store_true",
        help="Skip updating articles already logged as successful edits in app_logging/logs/edit.log.",
    )
    args = parser.parse_args()
    has_manual_county = args.article and args.state_fips and args.county_fips
    has_manual_place = args.article and args.state_fips and args.place_fips
    if args.county_fips and args.place_fips:
        parser.error("--county-fips cannot be combined with --place-fips.")
    if args.location and args.municipality:
        parser.error("--location cannot be combined with --municipality.")
    if args.municipality and args.place_fips:
        parser.error("--municipality cannot be combined with --place-fips.")
    if args.place_fips and not (args.article and args.state_fips):
        parser.error("--place-fips requires --article and --state-fips.")
    if args.state_postal and (args.article or args.location or args.municipality):
        parser.error("--state-postal cannot be combined with --article, --location, or --municipality.")
    if args.municipality_type and not args.state_postal:
        parser.error("--municipality-type can only be used with --state-postal.")
    if args.skip_location_parsing:
        if not args.article or not args.state_fips or not (args.county_fips or args.place_fips):
            parser.error(
                "--skip-location-parsing requires --article, --state-fips, and --county-fips or --place-fips."
            )
    if args.skip_location_parsing and args.location:
        parser.error("--skip-location-parsing cannot be combined with --location.")
    if args.skip_location_parsing and args.municipality:
        parser.error("--skip-location-parsing cannot be combined with --municipality.")
    if args.start_county_fips and not args.state_postal:
        parser.error("--start-county-fips can only be used with --state-postal.")
    if args.start_county_fips and args.municipality_type:
        parser.error("--start-county-fips cannot be used with --municipality-type.")
    if args.start_county_fips:
        if not args.start_county_fips.isdigit():
            parser.error("--start-county-fips must be numeric (e.g., 003).")
        if len(args.start_county_fips) > 3:
            parser.error("--start-county-fips must be a 3-digit county code.")
    if args.start_muni_fips and not args.state_postal:
        parser.error("--start-muni-fips can only be used with --state-postal.")
    if args.start_muni_fips and not args.municipality_type:
        parser.error("--start-muni-fips requires --municipality-type.")
    if args.start_muni_fips:
        if not args.start_muni_fips.isdigit():
            parser.error("--start-muni-fips must be numeric (e.g., 31050).")
        if len(args.start_muni_fips) > 5:
            parser.error("--start-muni-fips must be a 5-digit place code.")
    if not args.location and not args.municipality and not has_manual_county and not has_manual_place and not args.state_postal:
        parser.error(
            "Provide --location, --municipality, --state-postal, or specify --article, --state-fips, and --county-fips or --place-fips."
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


def _normalize_location_key(value: str) -> str:
    return " ".join(value.strip().split()).lower()


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

    def __init__(self, user_agent, log_file: Path = LOG_FILE):
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
    if args.model:
        os.environ["ACTIVE_MODEL"] = args.model

    active_model = os.getenv("ACTIVE_MODEL", DEFAULT_CODEX_MODEL)
    use_mini_prompt = active_model == "gpt-5.1-codex-mini"
    skip_successful_articles = (
        _load_successful_articles() if args.skip_logged_successes else set()
    )
    is_municipality = bool(args.municipality or args.place_fips)

    client = WikipediaClient(WP_BOT_USER_AGENT)
    client.login(WP_BOT_USER_NAME, WP_BOT_PASSWORD)

    try:
        if args.state_postal:
            if args.municipality_type:
                process_municipality_batch(
                    args.state_postal,
                    args.municipality_type,
                    client,
                    args,
                    use_mini_prompt,
                    start_muni_fips=args.start_muni_fips,
                    skip_successful_articles=skip_successful_articles,
                )
            else:
                process_state_batch(
                    args.state_postal,
                    client,
                    args,
                    use_mini_prompt,
                    start_county_fips=args.start_county_fips,
                    skip_successful_articles=skip_successful_articles,
                )
            return

        if is_municipality:
            if args.municipality and not args.skip_location_parsing:
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
                use_mini_prompt,
                skip_successful_articles=skip_successful_articles,
                location_kind="municipality",
            )
        else:
            if args.location and not args.skip_location_parsing:
                try:
                    article_title, state_fips, county_fips = derive_inputs_from_location(
                        args.location
                    )
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

            process_single_article_with_retries(
                article_title,
                state_fips,
                county_fips,
                args,
                client,
                use_mini_prompt,
                skip_successful_articles=skip_successful_articles,
            )
    except CodexUsageLimitError:
        print("Codex usage limit reached; stopping further processing.")
        sys.exit(1)


if __name__ == '__main__':
    main()
