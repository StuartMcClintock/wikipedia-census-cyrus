#!/usr/bin/env python3
"""
Fix misplaced {{increase}}/{{decrease}}/{{same}} tags inside multi-line estref fields
in {{US Census population}} templates within ==Demographics==.

Shows the proposed change and waits for Enter before applying edits.
Defaults to dry-run. Use --apply to edit Wikipedia.
"""

import argparse
import difflib
import json
import re
import sys
import time
from dataclasses import dataclass
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


@dataclass
class TemplateParam:
    name: Optional[str]
    raw: str
    prefix: Optional[str] = None
    value: Optional[str] = None
    trailing: Optional[str] = None


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


def _split_template_params(template: str) -> Tuple[str, List[str], str]:
    depth = 0
    link_depth = 0
    param_positions: List[int] = []
    outer_end = None

    i = 0
    while i < len(template) - 1:
        two = template[i:i + 2]
        if two == "{{":
            depth += 1
            i += 2
            continue
        if two == "}}":
            depth = max(0, depth - 1)
            i += 2
            if depth == 0 and outer_end is None:
                outer_end = i
            continue
        if two == "[[":
            link_depth += 1
            i += 2
            continue
        if two == "]]":
            link_depth = max(0, link_depth - 1)
            i += 2
            continue
        if template[i] == "|" and depth == 1 and link_depth == 0:
            param_positions.append(i)
        i += 1

    if outer_end is None:
        return template, [], ""

    if not param_positions:
        return template, [], ""

    close_start = max(0, outer_end - 2)
    prefix = template[:param_positions[0]]
    params = []
    for idx, pos in enumerate(param_positions):
        end = param_positions[idx + 1] if idx + 1 < len(param_positions) else close_start
        params.append(template[pos:end])
    suffix = template[close_start:]
    return prefix, params, suffix


def _parse_param(raw: str) -> TemplateParam:
    match = re.match(r"(\|\s*([^=|]+)\s*=\s*)(.*)", raw, flags=re.DOTALL)
    if not match:
        return TemplateParam(name=None, raw=raw)
    prefix = match.group(1)
    name = match.group(2).strip().lower()
    value = match.group(3)
    value_stripped = value.rstrip()
    trailing = value[len(value_stripped):]
    return TemplateParam(
        name=name,
        raw=raw,
        prefix=prefix,
        value=value_stripped,
        trailing=trailing,
    )


def _render_param(param: TemplateParam) -> str:
    if param.name is None or param.prefix is None or param.value is None:
        return param.raw
    trailing = param.trailing or ""
    return f"{param.prefix}{param.value}{trailing}"


def _collect_change_tags_with_positions(value: str) -> List[Tuple[str, int, str]]:
    tags: List[Tuple[str, int, str]] = []
    if not value:
        return tags
    for match in re.finditer(r"\{\{\s*([^}|]+)", value):
        name = " ".join(match.group(1).replace("_", " ").lower().split())
        tag_type = CHANGE_TAG_NAME_TO_TYPE.get(name)
        if tag_type:
            tags.append((tag_type, match.start(), match.group(0)))
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


def _append_tag_after_ref(value: str, tag_type: str) -> str:
    tag_text = f"{{{{{tag_type}}}}}"
    cleaned = _strip_change_tags(value or "")
    if not cleaned:
        return tag_text
    ref_close = cleaned.rfind("</ref>")
    if ref_close != -1:
        insert_at = ref_close + len("</ref>")
        return cleaned[:insert_at] + " " + tag_text + cleaned[insert_at:]
    return f"{cleaned} {tag_text}"


def _find_ref_spans(value: str) -> List[Tuple[int, int]]:
    spans: List[Tuple[int, int]] = []
    if not value:
        return spans
    for match in re.finditer(r"<ref\b[^>/]*?>", value, flags=re.IGNORECASE):
        start = match.start()
        end = value.find("</ref>", match.end())
        if end == -1:
            continue
        spans.append((start, end + len("</ref>")))
    return spans


def fix_estref_change_tag(template: str) -> Tuple[str, bool]:
    prefix, param_segments, suffix = _split_template_params(template)
    if not param_segments:
        return template, False

    params = [_parse_param(seg) for seg in param_segments]
    estref_param = next((p for p in params if p.name == "estref"), None)
    if estref_param is None:
        return template, False

    value = estref_param.value or ""
    tags = _collect_change_tags_with_positions(value)
    if not tags:
        return template, False

    ref_spans = _find_ref_spans(value)
    if not ref_spans:
        return template, False

    def _inside_ref(pos: int) -> bool:
        return any(start <= pos < end for start, end in ref_spans)

    if not any(_inside_ref(pos) for _, pos, _ in tags):
        return template, False

    desired_tag = tags[0][0]
    estref_param.value = _append_tag_after_ref(value, desired_tag)

    rebuilt = prefix + "".join(_render_param(p) for p in params) + suffix
    if rebuilt == template:
        return template, False
    return rebuilt, True


def update_census_templates_in_section(section_text: str) -> Tuple[str, int, List[str]]:
    updated = []
    cursor = 0
    total_changes = 0
    diffs: List[str] = []
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
        new_template, changed = fix_estref_change_tag(template)
        if changed and new_template == template:
            changed = False
        if changed:
            total_changes += 1
            diff_lines = list(
                difflib.unified_diff(
                    template.splitlines(),
                    new_template.splitlines(),
                    fromfile="before",
                    tofile="after",
                    lineterm="",
                )
            )
            diff = "\n".join(diff_lines).strip()
            if not diff:
                diff = (
                    "BEFORE:\n"
                    f"{template}\n\n"
                    "AFTER:\n"
                    f"{new_template}"
                )
            diffs.append(diff)
        updated.append(new_template)
        cursor = end
    return "".join(updated), total_changes, diffs


def update_demographics_section(wikitext: str) -> Tuple[str, int, List[str]]:
    parsed = ParsedWikitext(wikitext=wikitext)
    for index, entry in enumerate(parsed.sections):
        heading = entry[0]
        if heading in {"__lead__", "__content__"}:
            continue
        if heading.strip().lower() != "demographics":
            continue
        section_text = ParsedWikitext(sections=[entry]).to_wikitext()
        if not US_CENSUS_TEMPLATE_RE.search(section_text):
            return wikitext, 0, []
        updated_section, changes, diffs = update_census_templates_in_section(section_text)
        if changes == 0:
            return wikitext, 0, []
        fixed_sections = ParsedWikitext(wikitext=updated_section).sections
        replacement_entry = None
        for fixed_entry in fixed_sections:
            if fixed_entry[0] in {"__lead__", "__content__"}:
                continue
            replacement_entry = fixed_entry
            break
        if replacement_entry is None:
            return wikitext, 0, []
        parsed.sections[index] = replacement_entry
        return parsed.to_wikitext(), changes, diffs
    return wikitext, 0, []


def process_article(
    article_title: str,
    client: WikipediaClient,
    apply_changes: bool,
    summary: str,
) -> Tuple[bool, Optional[str]]:
    title, wikitext = client.fetch_article_wikitext(article_title)
    if wikitext.lstrip().lower().startswith("#redirect"):
        return False, f"Skipping '{title}' because it is a redirect."

    updated_text, changes, diffs = update_demographics_section(wikitext)
    if changes == 0:
        return False, f"No change: {title}"

    if diffs:
        print(f"\nProposed changes for: {title}\n")
        for diff in diffs:
            print(diff)
            print()

    if apply_changes:
        response = input("Press Enter to apply this change (or type anything to skip): ")
        if response.strip():
            return False, f"Skipped: {title}"
        result = client.edit_article_wikitext(title, updated_text, summary=summary)
        if result.get("edit", {}).get("result") == "Success":
            return True, f"Updated: {title} (fixed estref change tag formatting)"
        return False, f"Edit failed: {title} -> {result}"
    return True, f"Would update: {title} (fixed estref change tag formatting)"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix misplaced estimate change tags inside estref fields."
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
        default="Fix estimate change tag formatting in census table",
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
