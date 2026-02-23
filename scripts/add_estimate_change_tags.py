#!/usr/bin/env python3
"""
Add change tags (e.g., {{increase}}/{{decrease}}/{{same}}) to the estref
field in {{US Census population}} templates within the ==Demographics== section.

The tag is chosen by comparing the estimate to the most recent non-estimate
year value that precedes the estimate year.

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
from municipality.muni_type_classifier import find_template_block
from parser.parser import ParsedWikitext

WIKIPEDIA_ENDPOINT = "https://en.wikipedia.org/w/api.php"
FIPS_MAPPING_DIR = ROOT_DIR / "census_api" / "fips_mappings"
STATE_TO_FIPS_PATH = FIPS_MAPPING_DIR / "state_to_fips.json"
COUNTY_FIPS_DIR = FIPS_MAPPING_DIR / "county_to_fips"
MUNICIPALITY_FIPS_DIR = FIPS_MAPPING_DIR / "municipality_to_fips"
NON_STATE_POSTALS = {"AS", "GU", "MP", "PR", "VI", "DC"}

US_CENSUS_TEMPLATE_RE = re.compile(r"\{\{\s*US Census population", re.IGNORECASE)
CHANGE_TAG_SYNONYMS = {
    "increase": [
        "{{increase}}",
        "{{gain}}",
        "{{profit}}",
        "{{growth}}",
        "{{up}}",
        "{{augmentation}}",
        "{{IncreasePositive}}",
        "{{positive increase}}",
    ],
    "decrease": [
        "{{decrease}}",
        "{{loss}}",
        "{{LOSS}}",
        "{{down}}",
        "{{diminution}}",
        "{{DecreaseNegative}}",
        "{{negative decrease}}",
    ],
    "same": [
        "{{same}}",
        "{{steady}}",
        "{{nochange}}",
        "{{no change}}",
        "{{unchanged}}",
    ],
}

CHANGE_TAG_NAME_TO_TYPE = {}
for tag_type, names in CHANGE_TAG_SYNONYMS.items():
    for raw in names:
        stripped = raw.strip("{} ").replace("_", " ")
        normalized = " ".join(stripped.lower().split())
        CHANGE_TAG_NAME_TO_TYPE[normalized] = tag_type


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


def _extract_first_number(value: str) -> Optional[int]:
    if value is None:
        return None
    match = re.search(r"\d[\d,]*", value)
    if not match:
        return None
    try:
        return int(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _collect_change_tags(value: str) -> List[str]:
    if not value:
        return []
    tags = []
    for match in re.finditer(r"\{\{\s*([^}|]+)", value):
        name = " ".join(match.group(1).replace("_", " ").lower().split())
        tag_type = CHANGE_TAG_NAME_TO_TYPE.get(name)
        if tag_type:
            tags.append(tag_type)
    return tags


def _strip_change_tags(value: str) -> str:
    if not value:
        return value

    def _replace(match: re.Match) -> str:
        name = " ".join(match.group(1).replace("_", " ").lower().split())
        if name in CHANGE_TAG_NAME_TO_TYPE:
            return ""
        return match.group(0)

    cleaned = re.sub(r"\{\{\s*([^{}|]+)[^{}]*\}\}", _replace, value)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def _find_previous_year_value(lines: List[str], estyear: int) -> Optional[int]:
    best_year = None
    best_value = None
    for line in lines:
        match = re.match(r"^\s*\|\s*(\d{4})\s*=\s*(.*)$", line)
        if not match:
            continue
        year = int(match.group(1))
        if year >= estyear:
            continue
        value = _extract_first_number(match.group(2))
        if value is None:
            continue
        if best_year is None or year > best_year:
            best_year = year
            best_value = value
    return best_value


def _find_latest_year(lines: List[str]) -> Optional[int]:
    latest = None
    for line in lines:
        match = re.match(r"^\s*\|\s*(\d{4})\s*=", line)
        if not match:
            continue
        year = int(match.group(1))
        if latest is None or year > latest:
            latest = year
    return latest


def update_estimate_tag(template: str) -> Tuple[str, bool, str]:
    normalized, _ = normalize_us_census_template(template)
    lines = normalized.splitlines()

    estyear_idx = _line_index(lines, "estyear")
    estimate_idx = _line_index(lines, "estimate")
    estref_idx = _line_index(lines, "estref")
    if estyear_idx is None or estimate_idx is None:
        return template, False, "none"

    estyear_value = _parse_year(lines[estyear_idx])
    if estyear_value is None:
        return template, False, "none"

    latest_year = _find_latest_year(lines)
    if latest_year is not None and estyear_value < latest_year:
        for idx in sorted(
            [i for i in (estref_idx, estimate_idx, estyear_idx) if i is not None],
            reverse=True,
        ):
            del lines[idx]
        return "\n".join(lines), True, "estimate_removed"

    estimate_line = lines[estimate_idx]
    m = re.match(r"^(\s*\|\s*estimate\s*=\s*)(.*)$", estimate_line, flags=re.IGNORECASE)
    if not m:
        return template, False, "none"
    prefix, estimate_value = m.groups()

    estimate_number = _extract_first_number(estimate_value)
    if estimate_number is None:
        return template, False, "none"

    prev_value = _find_previous_year_value(lines, estyear_value)
    if prev_value is None:
        return template, False, "none"

    if estimate_number > prev_value:
        desired_tag = "increase"
    elif estimate_number < prev_value:
        desired_tag = "decrease"
    else:
        desired_tag = "same"

    estimate_tags = _collect_change_tags(estimate_value)
    estref_value = ""
    estref_prefix = ""
    if estref_idx is not None:
        estref_line = lines[estref_idx]
        m_ref = re.match(r"^(\s*\|\s*estref\s*=\s*)(.*)$", estref_line, flags=re.IGNORECASE)
        if m_ref:
            estref_prefix = m_ref.group(1)
            estref_value = m_ref.group(2)

    estref_tags = _collect_change_tags(estref_value)
    existing_tags = estimate_tags + estref_tags
    if existing_tags and all(tag == desired_tag for tag in existing_tags):
        return template, False, "none"

    cleaned_estimate = _strip_change_tags(estimate_value)
    if cleaned_estimate != estimate_value:
        lines[estimate_idx] = f"{prefix}{cleaned_estimate}"

    cleaned_estref = _strip_change_tags(estref_value)
    tag_text = f"{{{{{desired_tag}}}}}"
    if cleaned_estref:
        new_estref = f"{cleaned_estref} {tag_text}"
    else:
        new_estref = tag_text

    if estref_idx is not None and estref_prefix:
        lines[estref_idx] = f"{estref_prefix}{new_estref}"
    elif estref_idx is not None:
        indent = re.match(r"^(\s*)", lines[estref_idx]).group(1)
        lines[estref_idx] = f"{indent}|estref={new_estref}"
    else:
        insert_at = estimate_idx + 1
        indent = re.match(r"^(\s*)", lines[estimate_idx]).group(1)
        lines.insert(insert_at, f"{indent}|estref={new_estref}")

    return "\n".join(lines), True, "tag_updated"


def update_census_templates_in_section(section_text: str) -> Tuple[str, int, int]:
    updated = []
    cursor = 0
    total_changes = 0
    removed_estimates = 0
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
        new_template, changed, change_kind = update_estimate_tag(template)
        if changed:
            total_changes += 1
            if change_kind == "estimate_removed":
                removed_estimates += 1
        updated.append(new_template)
        cursor = end
    return "".join(updated), total_changes, removed_estimates


def update_demographics_section(wikitext: str) -> Tuple[str, int, int]:
    parsed = ParsedWikitext(wikitext=wikitext)
    for index, entry in enumerate(parsed.sections):
        heading = entry[0]
        if heading in {"__lead__", "__content__"}:
            continue
        if heading.strip().lower() != "demographics":
            continue
        section_text = ParsedWikitext(sections=[entry]).to_wikitext()
        if not US_CENSUS_TEMPLATE_RE.search(section_text):
            return wikitext, 0, 0
        updated_section, changes, removed = update_census_templates_in_section(section_text)
        if changes == 0:
            return wikitext, 0, 0
        fixed_sections = ParsedWikitext(wikitext=updated_section).sections
        replacement_entry = None
        for fixed_entry in fixed_sections:
            if fixed_entry[0] in {"__lead__", "__content__"}:
                continue
            replacement_entry = fixed_entry
            break
        if replacement_entry is None:
            return wikitext, 0, 0
        parsed.sections[index] = replacement_entry
        return parsed.to_wikitext(), changes, removed
    return wikitext, 0, 0


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

    updated_text, changes, removed = update_demographics_section(wikitext)
    if changes == 0:
        return False, f"No change: {title}"

    if apply_changes:
        summary_to_use = summary
        if removed and removed == changes:
            summary_to_use = "Remove outdated estimate fields from census table"
        elif removed:
            summary_to_use = "Update estimate change tag and remove outdated estimate fields"

        result = client.edit_article_wikitext(title, updated_text, summary=summary_to_use)
        if result.get("edit", {}).get("result") == "Success":
            if removed and removed == changes:
                return True, f"Removed outdated estimate fields: {title}"
            if removed:
                return True, f"Updated: {title} (estimate change tag + removed outdated estimate fields)"
            return True, f"Updated: {title} (estimate change tag)"
        return False, f"Edit failed: {title} -> {result}"
    if removed and removed == changes:
        return True, f"Would remove outdated estimate fields: {title}"
    if removed:
        return True, f"Would update: {title} (estimate change tag + removed outdated estimate fields)"
    return True, f"Would update: {title} (estimate change tag)"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add increase/decrease/same tags to estimate field in US Census population tables."
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
        default="Add estimate change tag to census table",
        help="Edit summary for --apply.",
    )
    args = parser.parse_args()

    if not args.counties and not args.municipality_type:
        parser.error("--municipality-type is required unless --counties is set.")

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
            items = (
                list(load_county_items(state_postal))
                if args.counties
                else list(load_municipality_items(state_postal, args.municipality_type))
            )
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
                    is_county=args.counties,
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
