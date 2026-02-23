#!/usr/bin/env python3
"""
Update 2023 population estimates in {{US Census population}} templates for counties.

If estyear is missing or earlier than 2023, set:
  |estyear=2023
  |estimate=<2023 POP estimate>
  |estref=<citation with Census API URL>

Only operates when the template is inside a ==Demographics== section.
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

from census_api.utils import strip_census_key
from credentials import WP_BOT_PASSWORD, WP_BOT_USER_AGENT, WP_BOT_USER_NAME, CENSUS_KEY
from municipality.muni_type_classifier import find_template_block
from parser.parser import ParsedWikitext

WIKIPEDIA_ENDPOINT = "https://en.wikipedia.org/w/api.php"
PEP_ENDPOINT = "https://api.census.gov/data/2023/pep/charv"
FIPS_MAPPING_DIR = ROOT_DIR / "census_api" / "fips_mappings"
STATE_TO_FIPS_PATH = FIPS_MAPPING_DIR / "state_to_fips.json"
COUNTY_FIPS_DIR = FIPS_MAPPING_DIR / "county_to_fips"
NON_STATE_POSTALS = {"AS", "GU", "MP", "PR", "VI", "DC"}
MAX_CENSUS_RETRIES = 3

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


def _split_state_postals(value: str) -> List[str]:
    parts = [part for part in re.split(r"[,\s]+", value.strip()) if part]
    if any(part.upper() == "ALL" for part in parts):
        data = json.loads(STATE_TO_FIPS_PATH.read_text())
        return sorted(postal for postal in data.keys() if postal not in NON_STATE_POSTALS)
    return [part.upper() for part in parts]


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


def _pep_url(state_fips: str, county_fips: str) -> str:
    params = {
        "get": "NAME,POP",
        "for": f"county:{county_fips.zfill(3)}",
        "in": f"state:{state_fips.zfill(2)}",
        "MONTH": "7",
        "YEAR": "2023",
        "UNIVERSE": "R",
        "AGE": "0000",
        "SEX": "0",
    }
    url = requests.Request("GET", PEP_ENDPOINT, params=params).prepare().url
    return strip_census_key(url)


def _fetch_county_estimate(state_fips: str, county_fips: str) -> int:
    params = {
        "get": "NAME,POP",
        "for": f"county:{county_fips.zfill(3)}",
        "in": f"state:{state_fips.zfill(2)}",
        "MONTH": "7",
        "YEAR": "2023",
        "UNIVERSE": "R",
        "AGE": "0000",
        "SEX": "0",
    }
    if CENSUS_KEY:
        params["key"] = CENSUS_KEY
    last_error = None
    for attempt in range(1, MAX_CENSUS_RETRIES + 1):
        response = requests.get(PEP_ENDPOINT, params=params, timeout=30)
        if response.status_code in {429, 500, 502, 503, 504}:
            last_error = RuntimeError(
                f"Census API HTTP {response.status_code} (attempt {attempt})."
            )
            time.sleep(0.5 * attempt)
            continue
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            safe_url = strip_census_key(response.url)
            raise RuntimeError(
                f"Census API HTTP {response.status_code} for {safe_url}."
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            content_type = response.headers.get("content-type", "")
            safe_url = strip_census_key(response.url)
            last_error = ValueError(
                "Census API returned non-JSON content "
                f"(content-type={content_type}, bytes={len(response.content)}), "
                f"url={safe_url}."
            )
            time.sleep(0.5 * attempt)
            continue
        if not payload or len(payload) < 2:
            last_error = ValueError("Census API returned no population rows.")
            time.sleep(0.5 * attempt)
            continue
        header = payload[0]
        row = payload[1]
        record = dict(zip(header, row))
        try:
            return int(record.get("POP"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Census API returned an invalid population value.") from exc
    if last_error is not None:
        raise last_error
    raise RuntimeError("Census API request failed with an unknown error.")


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


def _find_param_value(template: str, key: str) -> Optional[str]:
    pattern = re.compile(
        rf"\|\s*{re.escape(key)}\s*=\s*([^|\n}}]*)",
        flags=re.IGNORECASE,
    )
    match = pattern.search(template)
    if not match:
        return None
    return match.group(1).strip()


def _line_index(lines: List[str], key: str) -> Optional[int]:
    for idx, line in enumerate(lines):
        if re.match(rf"^\s*\|\s*{re.escape(key)}\s*=", line, flags=re.IGNORECASE):
            return idx
    return None


def _parse_year(value: str) -> Optional[int]:
    match = re.search(r"\d{4}", value or "")
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _update_line(lines: List[str], idx: int, key: str, value: str) -> bool:
    prefix = re.match(r"^(\s*)", lines[idx]).group(1)
    new_line = f"{prefix}|{key}={value}"
    if lines[idx] == new_line:
        return False
    lines[idx] = new_line
    return True


def _insert_after_year(lines: List[str]) -> int:
    last_year_idx = None
    for idx, line in enumerate(lines):
        m = re.match(r"^\s*\|\s*(\d{4})\s*=", line)
        if not m:
            continue
        year = int(m.group(1))
        if last_year_idx is None or year >= int(re.match(r"^\s*\|\s*(\d{4})\s*=", lines[last_year_idx]).group(1)):
            last_year_idx = idx
    if last_year_idx is not None:
        return last_year_idx + 1
    return 1 if lines else 0


def _insert_line(lines: List[str], idx: int, key: str, value: str) -> None:
    indent = re.match(r"^(\s*)", lines[idx - 1] if idx > 0 else "").group(1)
    lines.insert(idx, f"{indent}|{key}={value}")


def update_estimate_fields(template: str, population: int, citation: str) -> Tuple[str, bool]:
    raw_estyear = _find_param_value(template, "estyear")
    estyear_value = _parse_year(raw_estyear)

    should_update = raw_estyear is None or estyear_value is None or estyear_value < 2023
    if not should_update:
        return template, False

    normalized, changed = normalize_us_census_template(template)
    lines = normalized.splitlines()
    estyear_idx = _line_index(lines, "estyear")

    insert_at = _insert_after_year(lines)

    if estyear_idx is not None:
        if _update_line(lines, estyear_idx, "estyear", "2023"):
            changed = True
    else:
        _insert_line(lines, insert_at, "estyear", "2023")
        insert_at += 1
        changed = True

    estimate_idx = _line_index(lines, "estimate")
    if estimate_idx is not None:
        if _update_line(lines, estimate_idx, "estimate", str(population)):
            changed = True
    else:
        _insert_line(lines, insert_at, "estimate", str(population))
        insert_at += 1
        changed = True

    estref_idx = _line_index(lines, "estref")
    if estref_idx is not None:
        if _update_line(lines, estref_idx, "estref", citation):
            changed = True
    else:
        _insert_line(lines, insert_at, "estref", citation)
        changed = True

    return "\n".join(lines), changed


def update_census_templates_in_section(
    section_text: str, population: int, citation: str
) -> Tuple[str, int]:
    updated = []
    cursor = 0
    total_changes = 0
    while True:
        match = US_CENSUS_TEMPLATE_RE.search(section_text, cursor)
        if not match:
            updated.append(section_text[cursor:])
            break
        start = match.start()
        block = find_template_block(section_text, start)
        if not block:
            updated.append(section_text[cursor:])
            break
        end = block[1]
        updated.append(section_text[cursor:start])
        template = section_text[start:end]
        new_template, changed = update_estimate_fields(template, population, citation)
        if changed:
            total_changes += 1
        updated.append(new_template)
        cursor = end
    return "".join(updated), total_changes


def update_demographics_section(
    wikitext: str, population: int, citation: str
) -> Tuple[str, int]:
    parsed = ParsedWikitext(wikitext=wikitext)
    for index, entry in enumerate(parsed.sections):
        heading = entry[0]
        if heading in {"__lead__", "__content__"}:
            continue
        if heading.strip().lower() != "demographics":
            continue
        section_text = ParsedWikitext(sections=[entry]).to_wikitext()
        if not US_CENSUS_TEMPLATE_RE.search(section_text):
            return wikitext, 0
        updated_section, changes = update_census_templates_in_section(
            section_text, population, citation
        )
        if changes == 0:
            return wikitext, 0
        fixed_sections = ParsedWikitext(wikitext=updated_section).sections
        replacement_entry = None
        for fixed_entry in fixed_sections:
            if fixed_entry[0] in {"__lead__", "__content__"}:
                continue
            replacement_entry = fixed_entry
            break
        if replacement_entry is None:
            return wikitext, 0
        parsed.sections[index] = replacement_entry
        return parsed.to_wikitext(), changes
    return wikitext, 0


def build_estref(citation_url: str) -> str:
    today = datetime.utcnow().date()
    access_date = f"{today.strftime('%B')} {today.day}, {today.year}"
    return (
        "<ref name=\"Census2023PEP\">"
        "{{cite web|title=2023 Population Estimates (PEP)|"
        f"url={citation_url}|website=United States Census Bureau|"
        f"access-date={access_date}|df=mdy}}"
        "</ref>"
    )


def process_article(
    article_title: str,
    state_fips: str,
    county_fips: str,
    client: WikipediaClient,
    apply_changes: bool,
    summary: str,
) -> Tuple[bool, Optional[str]]:
    title, wikitext = client.fetch_article_wikitext(article_title)
    if wikitext.lstrip().lower().startswith("#redirect"):
        return False, f"Skipping '{title}' because it is a redirect."

    estimate = _fetch_county_estimate(state_fips, county_fips)
    citation_url = _pep_url(state_fips, county_fips)
    estref = build_estref(citation_url)

    updated_text, changes = update_demographics_section(wikitext, estimate, estref)
    if changes == 0:
        return False, f"No change: {title}"

    if apply_changes:
        result = client.edit_article_wikitext(title, updated_text, summary=summary)
        if result.get("edit", {}).get("result") == "Success":
            return True, f"Updated: {title} (2023 estimate)"
        return False, f"Edit failed: {title} -> {result}"
    return True, f"Would update: {title} (2023 estimate)"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update 2023 population estimates in US Census population tables for counties."
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
        default="Update 2023 population estimates in census table",
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
    if args.start_state:
        start_state = args.start_state.upper()
        state_postals = sorted(state_postals)
        if start_state not in state_postals:
            parser.error(f"--start-state '{args.start_state}' is not in the state list.")
        state_postals = state_postals[state_postals.index(start_state):]

    for state_postal in state_postals:
        try:
            items = list(load_county_items(state_postal))
        except FileNotFoundError as exc:
            errors += 1
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{timestamp} UTC] Error: {exc}")
            continue

        for name, state_fips, county_fips in items:
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
                    county_fips,
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
