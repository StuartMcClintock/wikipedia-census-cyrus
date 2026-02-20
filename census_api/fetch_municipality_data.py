"""
Fetch place-level demographic variables from the 2020 Census PL and DP APIs.
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import requests

from census_api.fetch_county_data import CensusFetchError

from census_api.constants import (
    DHC_ENDPOINT,
    DHC_FIELDS,
    DP_ENDPOINT,
    DP_FIELDS,
    PL_ENDPOINT,
    PL_FIELDS,
)
from census_api.utils import strip_census_key
from credentials import CENSUS_KEY

SCRIPT_DIR = Path(__file__).resolve().parent
STATE_TO_FIPS_PATH = SCRIPT_DIR / "fips_mappings" / "state_to_fips.json"
MUNICIPALITY_FIPS_DIR = SCRIPT_DIR / "fips_mappings" / "municipality_to_fips"


def _postal_from_state_fips(state_fips: str) -> str:
    data = json.loads(STATE_TO_FIPS_PATH.read_text())
    for postal, code in data.items():
        if code.split(":")[1] == state_fips:
            return postal
    return ""


def _place_name_from_codes(state_fips: str, place_fips: str) -> str:
    postal = _postal_from_state_fips(state_fips)
    if not postal:
        return ""
    state_dir = MUNICIPALITY_FIPS_DIR / postal
    if not state_dir.exists():
        return ""
    state_code = state_fips.zfill(2)
    place_code = place_fips.zfill(5)
    for type_dir in state_dir.iterdir():
        if not type_dir.is_dir():
            continue
        path = type_dir / "places.json"
        if not path.exists():
            continue
        mapping = json.loads(path.read_text())
        for name, codes in mapping.items():
            if (
                str(codes.get("state", "")).zfill(2) == state_code
                and str(codes.get("place", "")).zfill(5) == place_code
            ):
                return name
    return ""


def _fetch_table(endpoint: str, params: Dict[str, str]) -> Tuple[Dict[str, str], str]:
    """Request a Census API table and return a dict mapping headers to values."""
    try:
        request_params = dict(params)
        if CENSUS_KEY:
            request_params["key"] = CENSUS_KEY
        response = requests.get(endpoint, params=request_params, timeout=30)
        safe_url = strip_census_key(response.url)
        print(f"Requested: {safe_url}")
        response.raise_for_status()
        data: List[List[str]] = response.json()
        if len(data) < 2:
            raise ValueError(f"Census API returned no data rows for {params}")
        header, row = data[0], data[1]
        return dict(zip(header, row)), safe_url
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


def get_demographic_variables(state_fips: str, place_fips: str) -> Dict[str, object]:
    """Fetch PL and DP data and map into Wikipedia-style paragraph variables."""
    state = state_fips.zfill(2)
    place = place_fips.zfill(5)
    place_name = _place_name_from_codes(state, place) or f"place:{state}{place}"
    place_label = place_name.split(",", 1)[0].strip() if place_name else ""
    location_label = f"{place_name}"

    pl_params = {
        "get": PL_FIELDS,
        "for": f"place:{place}",
        "in": f"state:{state}",
    }
    dp_params = {
        "get": DP_FIELDS,
        "for": f"place:{place}",
        "in": f"state:{state}",
    }
    dhc_params = {
        "get": DHC_FIELDS,
        "for": f"place:{place}",
        "in": f"state:{state}",
    }

    try:
        print(f"Fetching PL data for {location_label} (state {state}, place {place})...")
        pl, pl_url = _fetch_table(PL_ENDPOINT, pl_params)
        print(f"Fetching DP data for {location_label} (state {state}, place {place})...")
        dp, dp_url = _fetch_table(DP_ENDPOINT, dp_params)
        print(f"Fetching DHC data for {location_label} (state {state}, place {place})...")
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

    race_white_count = int(pl["P1_003N"])
    race_black_count = int(pl["P1_004N"])
    race_aian_count = int(pl["P1_005N"])
    race_asian_count = int(pl["P1_006N"])
    race_nhpi_count = int(pl["P1_007N"])
    race_some_other_count = int(pl["P1_008N"])
    race_two_or_more_count = int(pl["P1_009N"])
    hispanic_any_race_count = int(pl["P2_002N"])
    hispanic_total_count = int(pl["P2_001N"])

    sex_male_total = int(dp["DP1_0025C"])
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

    urban_count_raw = _safe_float(dhc, "P2_002N")
    rural_count_raw = _safe_float(dhc, "P2_003N")
    urban_count = int(urban_count_raw) if urban_count_raw is not None else None
    rural_count = int(rural_count_raw) if rural_count_raw is not None else None
    urban_pct = _pct(urban_count, total_population) if urban_count is not None else None
    rural_pct = _pct(rural_count, total_population) if rural_count is not None else None

    result = {
        "place_name": place_label or place_name,
        "total_population": total_population,
        "total_households": total_households,
        "total_families": None,
        "total_housing_units": total_housing_units,
        "race_white_percent": _pct(race_white_count, total_population),
        "race_white_count": race_white_count,
        "race_black_percent": _pct(race_black_count, total_population),
        "race_black_count": race_black_count,
        "race_aian_percent": _pct(race_aian_count, total_population),
        "race_aian_count": race_aian_count,
        "race_asian_percent": _pct(race_asian_count, total_population),
        "race_asian_count": race_asian_count,
        "race_nhpi_percent": _pct(race_nhpi_count, total_population),
        "race_nhpi_count": race_nhpi_count,
        "race_some_other_percent": _pct(race_some_other_count, total_population),
        "race_some_other_count": race_some_other_count,
        "race_two_or_more_percent": _pct(race_two_or_more_count, total_population),
        "race_two_or_more_count": race_two_or_more_count,
        "hispanic_any_race_percent": _pct(hispanic_any_race_count, hispanic_total_count),
        "hispanic_any_race_count": hispanic_any_race_count,
        "households_with_children_under_18_percent": round(float(dp["DP1_0145P"]), 1),
        "married_couple_households_percent": _round1(_safe_float(dp, "DP1_0133P")),
        "female_householder_no_spouse_percent": round(float(dp["DP1_0141P"]), 1),
        "male_householder_no_spouse_percent": _round1(_safe_float(dp, "DP1_0137P")),
        "one_person_households_percent": round(
            float(dp["DP1_0138P"]) + float(dp["DP1_0142P"]), 1
        ),
        "living_alone_65_plus_households_percent": round(
            float(dp["DP1_0139P"]) + float(dp["DP1_0143P"]), 1
        ),
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
        "vacant_units_count": int(vacant_units_dp) if vacant_units_dp is not None else None,
        "homeowner_vacancy_rate_percent": homeowner_vacancy_rate,
        "rental_vacancy_rate_percent": rental_vacancy_rate,
        "urban_population_percent": urban_pct,
        "urban_population_count": urban_count,
        "rural_population_percent": rural_pct,
        "rural_population_count": rural_count,
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
        state_arg, place_arg = sys.argv[1], sys.argv[2]
    else:
        print(
            "Usage: python fetch_municipality_data.py <state_fips> <place_fips>\n"
            "Example: python fetch_municipality_data.py 40 55150",
            file=sys.stderr,
        )
        sys.exit(1)

    data = get_demographic_variables(state_arg, place_arg)
    print(json.dumps(data, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
