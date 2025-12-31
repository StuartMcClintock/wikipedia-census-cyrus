"""
Fetch county-level demographic variables from the 2020 Census PL and DP APIs.

Reference curl commands:
    curl "https://api.census.gov/data/2020/dec/pl?get=NAME,P1_001N,P1_003N,P1_004N,P1_005N,P1_006N,P1_008N,P1_009N,P2_001N,P2_002N,H1_001N,H1_002N&for=county:029&in=state:40"
    curl "https://api.census.gov/data/2020/dec/dp?get=NAME,DP1_0021P,DP1_0024P,DP1_0025C,DP1_0049C,DP1_0045C,DP1_0069C,DP1_0073C,DP1_0125P,DP1_0126P,DP1_0129P,DP1_0138P,DP1_0139P,DP1_0141P,DP1_0142P,DP1_0143P,DP1_0145P,DP1_0146P,DP1_0147C,DP1_0148C,DP1_0149C,DP1_0156C,DP1_0157C,DP1_0158C,DP1_0159P,DP1_0160P&for=county:029&in=state:40"
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import requests


class CensusFetchError(Exception):
    """Raised when fetching census data fails."""

from census_api.constants import (
    DHC_ENDPOINT,
    DHC_FIELDS,
    DP_ENDPOINT,
    DP_FIELDS,
    PL_ENDPOINT,
    PL_FIELDS,
)
from census_api.fips_mappings.get_county_fips import NON_COUNTY_POSTALS

SCRIPT_DIR = Path(__file__).resolve().parent
STATE_TO_FIPS_PATH = SCRIPT_DIR / "fips_mappings" / "state_to_fips.json"
COUNTY_FIPS_DIR = SCRIPT_DIR / "fips_mappings" / "county_to_fips"


def _postal_from_state_fips(state_fips: str) -> str:
    data = json.loads(STATE_TO_FIPS_PATH.read_text())
    for postal, code in data.items():
        if code.split(":")[1] == state_fips:
            return postal
    return ""


def _county_name_from_codes(state_fips: str, county_fips: str) -> str:
    postal = _postal_from_state_fips(state_fips)
    if not postal or postal in NON_COUNTY_POSTALS:
        return ""
    path = COUNTY_FIPS_DIR / f"{postal}.json"
    if not path.exists():
        return ""
    mapping = json.loads(path.read_text())
    target = f"county:{state_fips}{county_fips}"
    for name, code in mapping.items():
        if code == target:
            return name
    return ""


def _fetch_table(endpoint: str, params: Dict[str, str]) -> Tuple[Dict[str, str], str]:
    """Request a Census API table and return a dict mapping headers to values."""
    try:
        response = requests.get(endpoint, params=params, timeout=30)
        print(f"Requested: {response.url}")
        response.raise_for_status()
        data: List[List[str]] = response.json()
        if len(data) < 2:
            raise ValueError(f"Census API returned no data rows for {params}")
        header, row = data[0], data[1]
        return dict(zip(header, row)), response.url
    except Exception as exc:
        raise CensusFetchError(f"Failed request to {endpoint} with params {params}: {exc}") from exc


def _pct(part: int, whole: int) -> float:
    """Return a percentage rounded to one decimal place."""
    if whole == 0:
        return 0.0
    return round(100.0 * part / whole, 1)


def _safe_float(data: Dict[str, str], key: str):
    """Return float value for key or None if missing/invalid."""
    value = data.get(key)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _round1(value):
    """Round a float to one decimal place, preserving None."""
    if value is None:
        return None
    return round(value, 1)


def get_demographic_variables(state_fips: str, county_fips: str) -> Dict[str, object]:
    """Fetch PL and DP data and map into Wikipedia-style paragraph variables."""
    state = state_fips.zfill(2)
    county = county_fips.zfill(3)
    county_name = _county_name_from_codes(state, county) or f"county:{state}{county}"
    location_label = f"{county_name}"

    pl_params = {
        "get": PL_FIELDS,
        "for": f"county:{county}",
        "in": f"state:{state}",
    }
    dp_params = {
        "get": DP_FIELDS,
        "for": f"county:{county}",
        "in": f"state:{state}",
    }
    dhc_params = {
        "get": DHC_FIELDS,
        "for": f"county:{county}",
        "in": f"state:{state}",
    }

    try:
        print(f"Fetching PL data for {location_label} (state {state}, county {county})...")
        pl, pl_url = _fetch_table(PL_ENDPOINT, pl_params)
        print(f"Fetching DP data for {location_label} (state {state}, county {county})...")
        dp, dp_url = _fetch_table(DP_ENDPOINT, dp_params)
        print(f"Fetching DHC data for {location_label} (state {state}, county {county})...")
        dhc, dhc_url = _fetch_table(DHC_ENDPOINT, dhc_params)
    except Exception as exc:
        raise CensusFetchError(f"Failed to fetch census data for {location_label}: {exc}") from exc

    total_population = int(pl["P1_001N"])
    total_housing_units = (
        int(dp["DP1_0147C"]) if dp.get("DP1_0147C") not in (None, "") else int(pl["H1_001N"])
    )
    total_households = (
        int(dp["DP1_0148C"]) if dp.get("DP1_0148C") not in (None, "") else int(pl["H1_002N"])
    )

    sex_male_total = int(dp["DP1_0025C"])
    # Additional derived metrics from DP (with graceful degradation if missing).
    owner_pct = _round1(_safe_float(dp, "DP1_0159P"))
    renter_pct = _round1(_safe_float(dp, "DP1_0160P"))

    total_units_dp = _safe_float(dp, "DP1_0147C")
    vacant_units_dp = _safe_float(dp, "DP1_0149C")
    if (
        total_units_dp is not None
        and vacant_units_dp is not None
        and total_units_dp > 0
    ):
        vacant_units_percent = round(100.0 * vacant_units_dp / total_units_dp, 1)
    else:
        vacant_units_percent = None

    homeowner_vacancy_rate = _round1(_safe_float(dp, "DP1_0156C"))
    rental_vacancy_rate = _round1(_safe_float(dp, "DP1_0157C"))

    group_quarters_percent = _round1(_safe_float(dp, "DP1_0125P"))
    institutional_group_quarters_percent = _round1(_safe_float(dp, "DP1_0126P"))
    noninstitutional_group_quarters_percent = _round1(_safe_float(dp, "DP1_0129P"))

    sex_female_total = int(dp["DP1_0049C"])
    sex_male_18 = int(dp["DP1_0045C"])
    sex_female_18 = int(dp["DP1_0069C"])

    urban_count = _safe_float(dhc, "P2_002N")
    rural_count = _safe_float(dhc, "P2_003N")
    urban_pct = _pct(int(urban_count), total_population) if urban_count is not None else None
    rural_pct = _pct(int(rural_count), total_population) if rural_count is not None else None

    result = {
        "total_population": total_population,
        "total_households": total_households,
        # Could be sourced from other census products (e.g., DHC or ACS) if needed.
        "total_families": None,
        "total_housing_units": total_housing_units,
        "race_white_percent": _pct(int(pl["P1_003N"]), total_population),
        "race_black_percent": _pct(int(pl["P1_004N"]), total_population),
        "race_aian_percent": _pct(int(pl["P1_005N"]), total_population),
        "race_asian_percent": _pct(int(pl["P1_006N"]), total_population),
        "race_nhpi_percent": _pct(int(pl["P1_007N"]), total_population),
        "race_some_other_percent": _pct(int(pl["P1_008N"]), total_population),
        "race_two_or_more_percent": _pct(int(pl["P1_009N"]), total_population),
        "hispanic_any_race_percent": _pct(int(pl["P2_002N"]), int(pl["P2_001N"])),
        "households_with_children_under_18_percent": round(float(dp["DP1_0145P"]), 1),
        # Requires additional census tables; set to None for now.
        "married_couple_households_percent": None,
        "married_couple_households_percent": _round1(_safe_float(dp, "DP1_0133P")),
        "female_householder_no_spouse_percent": round(float(dp["DP1_0141P"]), 1),
        "male_householder_no_spouse_percent": _round1(_safe_float(dp, "DP1_0137P")),
        "one_person_households_percent": round(
            float(dp["DP1_0138P"]) + float(dp["DP1_0142P"]), 1
        ),
        "living_alone_65_plus_households_percent": round(
            float(dp["DP1_0139P"]) + float(dp["DP1_0143P"]), 1
        ),
        # Additional household size metrics are not available from PL/DP.
        "average_household_size": None,
        "average_family_size": None,
        "age_under_18_percent": round(100.0 - float(dp["DP1_0021P"]), 1),
        "age_65_plus_percent": round(float(dp["DP1_0024P"]), 1),
        "age_median_years": float(dp["DP1_0073C"]),
        "sex_ratio_males_per_100_females": round(
            100.0 * sex_male_total / sex_female_total, 1
        )
        if sex_female_total
        else None,
        "sex_ratio_18_plus_males_per_100_females": round(
            100.0 * sex_male_18 / sex_female_18, 1
        )
        if sex_female_18
        else None,
        "owner_occupied_percent": owner_pct,
        "renter_occupied_percent": renter_pct,
        "vacant_units_percent": vacant_units_percent,
        "homeowner_vacancy_rate_percent": homeowner_vacancy_rate,
        "rental_vacancy_rate_percent": rental_vacancy_rate,
        "urban_population_percent": urban_pct,
        "rural_population_percent": rural_pct,
        "group_quarters_percent": group_quarters_percent,
        "institutional_group_quarters_percent": institutional_group_quarters_percent,
        "noninstitutional_group_quarters_percent": noninstitutional_group_quarters_percent,
    }

    result["_pl_source_url"] = pl_url
    result["_dp_source_url"] = dp_url
    result["_dhc_source_url"] = dhc_url

    return result


def main() -> None:
    if len(sys.argv) >= 3:
        state_arg, county_arg = sys.argv[1], sys.argv[2]
    else:
        print(
            "Usage: python fetch_county_data.py <state_fips> <county_fips>\n"
            "Example: python fetch_county_data.py 40 029",
            file=sys.stderr,
        )
        sys.exit(1)

    data = get_demographic_variables(state_arg, county_arg)
    print(json.dumps(data, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
