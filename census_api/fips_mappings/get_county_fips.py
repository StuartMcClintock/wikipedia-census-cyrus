import json
from pathlib import Path
from typing import Dict

import requests

from credentials import CENSUS_KEY

BASE_URL = "https://api.census.gov/data/2020/dec/pl"
SCRIPT_DIR = Path(__file__).resolve().parent
STATE_TO_FIPS_PATH = SCRIPT_DIR / "state_to_fips.json"
OUTPUT_DIR = SCRIPT_DIR / "county_to_fips"
NON_COUNTY_POSTALS = {"AS", "GU", "MP", "PR", "VI"}


def load_states() -> Dict[str, str]:
    """Return mapping of state postal code -> census state code (e.g., state:01)."""
    return json.loads(STATE_TO_FIPS_PATH.read_text())


def fetch_counties(state_code: str) -> Dict[str, str]:
    """
    Fetch NAME and county code pairs for a state (state_code looks like 'state:01').
    Returns {county_name: 'county:SSCCC'}.
    """
    state_fp = state_code.split(":")[1]
    params = {
        "get": "NAME",
        "for": "county:*",
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
    county_idx = header.index("county")

    county_map: Dict[str, str] = {}
    for row in rows:
        county_name = row[name_idx]
        county_code = row[county_idx]
        county_map[county_name] = f"county:{state_fp}{county_code}"
    return county_map


def write_state_file(state_postal: str, mapping: Dict[str, str]) -> None:
    """
    Persist a state's county mapping into county_to_fips/<state_postal>.json.
    Re-running the script overwrites existing files without duplication.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{state_postal}.json"
    path.write_text(json.dumps(mapping, indent=2, ensure_ascii=False) + "\n")


def main() -> None:
    states = load_states()
    for postal_code, state_code in states.items():
        if postal_code in NON_COUNTY_POSTALS:
            print(f"Skipping {postal_code} (no county-level FIPS).")
            continue
        print(f"Fetching counties for {postal_code} ({state_code})...")
        county_map = fetch_counties(state_code)
        write_state_file(postal_code, county_map)
    print("County FIPS files updated.")


if __name__ == "__main__":
    main()
