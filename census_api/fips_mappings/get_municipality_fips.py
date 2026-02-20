import json
from pathlib import Path
from typing import Dict

import requests

from credentials import CENSUS_KEY

BASE_URL = "https://api.census.gov/data/2020/dec/pl"
SCRIPT_DIR = Path(__file__).resolve().parent
STATE_TO_FIPS_PATH = SCRIPT_DIR / "state_to_fips.json"
OUTPUT_DIR = SCRIPT_DIR / "municipality_to_fips"

PLACE_AND_CDP_SUFFIXES = [
    # Incorporated place legal descriptions
    "city",
    "town",
    "village",
    "borough",
    "municipality",
    "city and borough",
    "corporation",
    # Consolidated / special government forms that show up for some places
    "(balance)",
    "consolidated government",
    "consolidated government (balance)",
    "metropolitan government",
    "metropolitan government (balance)",
    "metro government",
    "unified government",
    "unified government (balance)",
    "urban county",
    # CDP / PR-specific CDP descriptors
    "CDP",
    "comunidad",
    "zona urbana",
]

_SORTED_SUFFIXES = sorted(PLACE_AND_CDP_SUFFIXES, key=len, reverse=True)


def load_states() -> Dict[str, str]:
    """Return mapping of state postal code -> census state code (e.g., state:01)."""
    return json.loads(STATE_TO_FIPS_PATH.read_text())


def _split_place_name(place_name: str) -> (str, str):
    """
    Return (clean_name, place_type) using the suffix from the name before the first comma.
    Uses a longest-match strategy to prefer more specific suffixes.
    """
    prefix = place_name.split(",", 1)[0].strip()
    remainder = place_name.split(",", 1)[1].strip() if "," in place_name else ""
    prefix_lower = prefix.lower()
    for suffix in _SORTED_SUFFIXES:
        if prefix_lower.endswith(suffix.lower()):
            stripped_prefix = prefix[: -len(suffix)].rstrip()
            if stripped_prefix:
                cleaned = f"{stripped_prefix}, {remainder}" if remainder else stripped_prefix
            else:
                cleaned = place_name
            return cleaned, suffix
    return place_name, "unknown"


def fetch_places(state_code: str) -> Dict[str, Dict[str, Dict[str, str]]]:
    """
    Fetch NAME/place code pairs for a state (state_code looks like 'state:01').
    Returns {place_type: {place_name: {"state": "SS", "place": "PPPPP"}}}.
    """
    state_fp = state_code.split(":", 1)[1]
    params = {
        "get": "NAME,P1_001N",
        "for": "place:*",
        "in": f"state:{state_fp}",
    }
    request_params = dict(params)
    if CENSUS_KEY:
        request_params["key"] = CENSUS_KEY
    response = requests.get(BASE_URL, params=request_params, timeout=30)
    response.raise_for_status()
    if not response.text.strip():
        return {}
    try:
        data = response.json()
    except ValueError as exc:  # pragma: no cover - defensive logging
        raise RuntimeError(f"Failed to parse response for {state_code}: {response.text[:200]}") from exc
    header, rows = data[0], data[1:]
    name_idx = header.index("NAME")
    pop_idx = header.index("P1_001N")
    state_idx = header.index("state")
    place_idx = header.index("place")

    place_map: Dict[str, Dict[str, Dict[str, str]]] = {}
    for row in rows:
        place_name = row[name_idx]
        population = row[pop_idx]
        state_fp_row = row[state_idx].zfill(2)
        place_code = row[place_idx].zfill(5)
        cleaned_name, place_type = _split_place_name(place_name)
        place_map.setdefault(place_type, {})[cleaned_name] = {
            "state": state_fp_row,
            "place": place_code,
            "population": population,
        }
    return place_map


def write_state_files(state_postal: str, mapping: Dict[str, Dict[str, Dict[str, str]]]) -> None:
    """
    Persist a state's place mapping into municipality_to_fips/<state>/<type>/places.json.
    Re-running the script overwrites existing files without duplication.
    """
    state_dir = OUTPUT_DIR / state_postal
    for place_type, entries in sorted(mapping.items()):
        if not entries:
            continue
        type_dir = state_dir / place_type
        type_dir.mkdir(parents=True, exist_ok=True)
        path = type_dir / "places.json"
        path.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n")


def main() -> None:
    states = load_states()
    for postal_code, state_code in states.items():
        print(f"Fetching places for {postal_code} ({state_code})...")
        place_map = fetch_places(state_code)
        write_state_files(postal_code, place_map)
    print("Municipality FIPS files updated.")


if __name__ == "__main__":
    main()
