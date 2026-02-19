#!/usr/bin/env python3
"""
Update 2020 census population in infoboxes for municipalities or counties.

For municipalities, validate the article type matches the expected type from
the FIPS mapping before editing.

Defaults to dry-run. Use --apply to edit Wikipedia.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

import requests

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from census_api.constants import PL_ENDPOINT
from credentials import WP_BOT_PASSWORD, WP_BOT_USER_AGENT, WP_BOT_USER_NAME, CENSUS_KEY
from municipality.muni_type_classifier import determine_municipality_type, find_template_block

WIKIPEDIA_ENDPOINT = "https://en.wikipedia.org/w/api.php"
FIPS_MAPPING_DIR = ROOT_DIR / "census_api" / "fips_mappings"
STATE_TO_FIPS_PATH = FIPS_MAPPING_DIR / "state_to_fips.json"
COUNTY_FIPS_DIR = FIPS_MAPPING_DIR / "county_to_fips"
MUNICIPALITY_FIPS_DIR = FIPS_MAPPING_DIR / "municipality_to_fips"
NON_STATE_POSTALS = {"AS", "GU", "MP", "PR", "VI"}


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


def _fetch_place_population(state_fips: str, place_fips: str) -> int:
    state = state_fips.zfill(2)
    place = place_fips.zfill(5)
    params = {
        "get": "NAME,P1_001N",
        "for": f"place:{place}",
        "in": f"state:{state}",
    }
    if CENSUS_KEY:
        params["key"] = CENSUS_KEY
    try:
        response = requests.get(PL_ENDPOINT, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise ValueError("Census API request failed.") from exc
    if not payload or len(payload) < 2:
        raise ValueError("Census API returned no population rows.")
    header = payload[0]
    row = payload[1]
    record = dict(zip(header, row))
    try:
        population = int(record.get("P1_001N"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Census API returned an invalid population value.") from exc
    return population


def _fetch_county_population(state_fips: str, county_fips: str) -> int:
    state = state_fips.zfill(2)
    county = county_fips.zfill(3)
    params = {
        "get": "NAME,P1_001N",
        "for": f"county:{county}",
        "in": f"state:{state}",
    }
    if CENSUS_KEY:
        params["key"] = CENSUS_KEY
    try:
        response = requests.get(PL_ENDPOINT, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise ValueError("Census API request failed.") from exc
    if not payload or len(payload) < 2:
        raise ValueError("Census API returned no population rows.")
    header = payload[0]
    row = payload[1]
    record = dict(zip(header, row))
    try:
        population = int(record.get("P1_001N"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Census API returned an invalid population value.") from exc
    return population


def _find_infobox_with_population(wikitext: str) -> Optional[Tuple[int, int, str]]:
    for match in re.finditer(r"\{\{\s*Infobox", wikitext, flags=re.IGNORECASE):
        block = find_template_block(wikitext, match.start())
        if not block:
            continue
        start, end = block
        template = wikitext[start:end]
        if (
            re.search(r"^\s*\|\s*population_total\s*=", template, flags=re.IGNORECASE | re.MULTILINE)
            or re.search(r"^\s*\|\s*population_as_of\s*=", template, flags=re.IGNORECASE | re.MULTILINE)
            or re.search(r"^\s*\|\s*pop\s*=", template, flags=re.IGNORECASE | re.MULTILINE)
            or re.search(r"^\s*\|\s*census\s*yr\s*=", template, flags=re.IGNORECASE | re.MULTILINE)
        ):
            return start, end, template
    return None


def _format_population(value: int, template_value: str) -> str:
    return str(value)


def _update_year_field(template: str, key: str) -> Tuple[str, bool]:
    pattern = re.compile(
        rf"(^\s*\|\s*{re.escape(key)}\s*=\s*)([^\n]*?)(\s*(?:<!--.*?-->\s*)?)$",
        flags=re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(template)
    if not match:
        return template, False
    prefix, current, trailing = match.group(1), match.group(2), match.group(3)
    if "2020" in current:
        return template, False
    if key.lower() == "population_as_of":
        use_link = "[[" in current or "census" in current.lower()
        new_value = "[[2020 United States census|2020]]" if use_link else "2020"
    else:
        new_value = "2020"
    new_line = f"{prefix}{new_value}{trailing}"
    updated = template[:match.start()] + new_line + template[match.end():]
    return updated, True


def _update_population_field(
    template: str, key: str, population: int
) -> Tuple[str, bool, bool]:
    pattern = re.compile(
        rf"(^\s*\|\s*{re.escape(key)}\s*=\s*)([^\n]*?)(\s*(?:<!--.*?-->\s*)?)"
        r"(?:\n([ \t]+(?!\|)[^\n]*))?$",
        flags=re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(template)
    if not match:
        return template, False, False
    prefix, current, trailing, continuation = (
        match.group(1),
        match.group(2),
        match.group(3),
        match.group(4),
    )
    formatted = _format_population(population, current)
    combined = current
    has_continuation = bool(continuation)
    if continuation:
        combined = (current + " " + continuation).strip()
    combined_no_comments = re.sub(r"<!--.*?-->", "", combined, flags=re.DOTALL).strip()
    current_number_match = re.search(r"\d[\d,]*", combined)
    if current_number_match:
        current_number_raw = current_number_match.group(0).replace(",", "")
        try:
            current_number = int(current_number_raw)
        except ValueError:
            current_number = None
        if current_number == population and not has_continuation:
            return template, False, False
        new_value = re.sub(r"\d[\d,]*", formatted, combined, count=1)
        normalization_only = current_number == population
    else:
        if combined_no_comments == "":
            new_value = formatted
        else:
            new_value = (formatted + " " + current).rstrip()
        normalization_only = False
    if new_value == current:
        return template, False, False
    new_line = f"{prefix}{new_value}{trailing}"
    updated = template[:match.start()] + new_line + template[match.end():]
    return updated, True, normalization_only


def _insert_population_total(template: str, population: int) -> Tuple[str, bool, bool]:
    lines = template.splitlines()
    insert_at = None
    has_population_as_of = any(
        re.match(r"^\s*\|\s*population_as_of\s*=", line, flags=re.IGNORECASE)
        for line in lines
    )
    for idx, line in enumerate(lines):
        if re.match(r"^\s*\|\s*population_as_of\s*=", line, flags=re.IGNORECASE):
            insert_at = idx + 1
            break
    if insert_at is None:
        for idx, line in enumerate(lines):
            if re.match(r"^\s*\|\s*census\s*yr\s*=", line, flags=re.IGNORECASE):
                insert_at = idx + 1
                break
    if insert_at is None:
        for idx, line in enumerate(lines):
            if re.match(r"^\s*\|\s*area_", line, flags=re.IGNORECASE):
                insert_at = idx
                break
    if insert_at is None:
        insert_at = len(lines) - 1

    indent_match = re.match(r"^(\s*)", lines[insert_at - 1] if insert_at > 0 else "")
    indent = indent_match.group(1) if indent_match else ""
    inserted_as_of = False
    if not has_population_as_of:
        as_of_line = f"{indent}| population_as_of = [[2020 United States census|2020]]"
        lines.insert(insert_at, as_of_line)
        insert_at += 1
        inserted_as_of = True
    new_line = f"{indent}| population_total = {population}"
    lines.insert(insert_at, new_line)
    return "\n".join(lines), True, inserted_as_of


def _normalize_infobox_field_lines(template: str) -> Tuple[str, bool]:
    lines = template.splitlines()
    changed = False
    normalized: List[str] = []

    def find_field_starts(line: str) -> List[int]:
        positions: List[int] = []
        i = 0
        depth = 0
        n = len(line)
        while i < n:
            two = line[i:i + 2]
            if two == "{{":
                depth += 1
                i += 2
                continue
            if two == "}}":
                depth = max(0, depth - 1)
                i += 2
                continue
            if depth == 0 and line[i] == "|":
                if i == 0 or line[i - 1].isspace():
                    m = re.match(r"\|\s*[^=\n|]+\s*=", line[i:])
                    if m:
                        positions.append(i)
                        i += m.end()
                        continue
            i += 1
        return positions

    for line in lines:
        positions = find_field_starts(line)
        if len(positions) <= 1:
            normalized.append(line)
            continue
        indent = re.match(r"^(\s*)", line).group(1)
        for i, pos in enumerate(positions):
            end = positions[i + 1] if i + 1 < len(positions) else len(line)
            segment = line[pos:end]
            if i == 0:
                segment = line[:pos] + segment
            else:
                segment = indent + segment.lstrip()
            normalized.append(segment.rstrip())
        changed = True
    return "\n".join(normalized), changed


def update_infobox_population(
    template: str, population: int
) -> Tuple[str, bool, bool]:
    updated, did_normalize_lines = _normalize_infobox_field_lines(template)
    changed = did_normalize_lines
    non_normalization_change = False
    formatting_change = did_normalize_lines
    has_population_total = bool(
        re.search(r"^\s*\|\s*population_total\s*=", updated, flags=re.IGNORECASE | re.MULTILINE)
    )
    if re.search(r"^\s*\|\s*population_as_of\s*=", updated, flags=re.IGNORECASE | re.MULTILINE):
        updated, did_change = _update_year_field(updated, "population_as_of")
        changed = changed or did_change
        non_normalization_change = non_normalization_change or did_change
    if re.search(r"^\s*\|\s*census\s*yr\s*=", updated, flags=re.IGNORECASE | re.MULTILINE):
        updated, did_change = _update_year_field(updated, "census yr")
        changed = changed or did_change
        non_normalization_change = non_normalization_change or did_change

    if has_population_total:
        updated, did_change, normalized = _update_population_field(
            updated, "population_total", population
        )
        changed = changed or did_change
        if did_change and not normalized:
            non_normalization_change = True
        if did_change and normalized:
            formatting_change = True
    else:
        updated, did_insert, did_insert_as_of = _insert_population_total(
            updated, population
        )
        if did_insert or did_insert_as_of:
            changed = True
            non_normalization_change = True

    normalization_only = changed and not non_normalization_change
    if normalization_only and not formatting_change:
        normalization_only = False
    return updated, changed, normalization_only


def _print_type_mismatch(article_title: str, expected_type: str, detected: Dict[str, object]) -> None:
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    display_title = article_title.replace("_", " ")
    reasons = detected.get("reasons") or []
    confidence = detected.get("confidence", "unknown")
    detected_type = detected.get("type", "unknown")
    reason_text = "\n  - ".join(reasons) if reasons else "No reasons supplied."
    print(
        f"[{timestamp} UTC] Skipping '{display_title}' (expected type '{expected_type}', "
        f"detected '{detected_type}' with {confidence} confidence).\n  - {reason_text}\n"
    )


def process_article(
    article_title: str,
    state_fips: str,
    locality_fips: str,
    client: WikipediaClient,
    expected_muni_type: Optional[str],
    is_county: bool,
    apply_changes: bool,
    summary: str,
    summary_normalize: str,
) -> Tuple[bool, Optional[str]]:
    title, wikitext = client.fetch_article_wikitext(article_title)
    if wikitext.lstrip().lower().startswith("#redirect"):
        return False, f"Skipping '{title}' because it is a redirect."

    if not is_county:
        if expected_muni_type is None:
            return False, f"Skipping '{title}' because expected municipality type is missing."
        detected = determine_municipality_type(wikitext)
        detected_type = (detected.get("type") or "").strip().lower()
        expected_type = expected_muni_type.strip().lower()
        if detected_type != expected_type:
            _print_type_mismatch(title, expected_muni_type, detected)
            return False, None

    infobox_block = _find_infobox_with_population(wikitext)
    if not infobox_block:
        return False, f"Skipping '{title}' (no infobox with population fields found)."
    start, end, template = infobox_block

    population = (
        _fetch_county_population(state_fips, locality_fips)
        if is_county
        else _fetch_place_population(state_fips, locality_fips)
    )

    updated_template, changed, normalization_only = update_infobox_population(
        template, population
    )
    if not changed:
        return False, f"No change: {title}"

    new_wikitext = wikitext[:start] + updated_template + wikitext[end:]
    if apply_changes:
        summary_to_use = summary_normalize if normalization_only else summary
        result = client.edit_article_wikitext(
            title, new_wikitext, summary=summary_to_use
        )
        if result.get("edit", {}).get("result") == "Success":
            return True, f"Updated: {title} (population {population:,})"
        return False, f"Edit failed: {title} -> {result}"
    return True, f"Would update: {title} (population {population:,})"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix 2020 census population in infoboxes for municipalities or counties."
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
        default="Update 2020 census population in infobox",
        help="Edit summary for --apply.",
    )
    parser.add_argument(
        "--summary-normalize",
        type=str,
        default="Normalize infobox population field formatting",
        help="Edit summary when only formatting changes are applied.",
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
                expected_type = None
                is_county = True
            else:
                items = list(load_municipality_items(state_postal, args.municipality_type))
                expected_type = args.municipality_type
                is_county = False
        except FileNotFoundError as exc:
            errors += 1
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{timestamp} UTC] Error: {exc}")
            continue

        for name, state_fips, local_fips in items:
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
                    state_fips,
                    local_fips,
                    client,
                    expected_type,
                    is_county=is_county,
                    apply_changes=args.apply,
                    summary=args.summary,
                    summary_normalize=args.summary_normalize,
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
