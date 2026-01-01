"""
Generate natural-language census paragraphs for a county using 2020 PL/DP data.
"""

TEMPLATE = '''As of the 2020 United States census, the county had a population of [total_population]. Of the residents,
  [age_under_18_percent]% were under the age of 18 and [age_65_plus_percent]% were 65 years of age or older; the median age was [age_median_years] years. For every 100 females
  there were [sex_ratio_males_per_100_females] males, and for every 100 females age 18 and over there were [sex_ratio_18_plus_males_per_100_females] males.

  The racial makeup of the county was [race_white_percent]% White, [race_black_percent]% Black or African American, [race_aian_percent]% American Indian and Alaska Native,
  [race_asian_percent]% Asian, [race_some_other_percent]% from some other race, and [race_two_or_more_percent]% from two or more races. Hispanic or Latino residents of any race
  comprised [hispanic_any_race_percent]% of the population.

  There were [total_households] households in the county, of which [households_with_children_under_18_percent]% had children under the age of 18 living with them. Married-couple
  households accounted for [married_couple_households_percent]% of all households, and [female_householder_no_spouse_percent]% had a female householder with no spouse or partner
  present. About [one_person_households_percent]% of all households were made up of individuals, and [living_alone_65_plus_households_percent]% had someone living alone who was
  65 years of age or older. The average household size was [average_household_size], and the average family size was [average_family_size]; there were [total_families] families
  residing in the county.

  There were [total_housing_units] housing units, of which [vacant_units_percent]% were vacant. Among occupied housing units, [owner_occupied_percent]% were owner-occupied and
  [renter_occupied_percent]% were renter-occupied. The homeowner vacancy rate was [homeowner_vacancy_rate_percent]%, and the rental vacancy rate was
  [rental_vacancy_rate_percent]%.'''

import datetime
import sys
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from census_api.constants import (
    CITATION_DETAILS,
    CITATION_SOURCES,
    DHC_ENDPOINT,
    DP_ENDPOINT,
    PL_ENDPOINT,
)
from census_api.fetch_county_data import get_demographic_variables, CensusFetchError

today = datetime.date.today()
ACCESS_DATE = f"{today.strftime('%B')} {today.day}, {today.year}"

LINK_REPLACEMENTS = [
    (
        "2020 United States census",
        "[[2020 United States census|2020 census]]",
    ),
    (" White", " [[White Americans|White]]"),
    (
        "American Indian and Alaska Native",
        "[[Native Americans in the United States|American Indian and Alaska Native]]",
    ),
    ("Native Hawaiian", "[[Native Hawaiians|Native Hawaiian]]"),
    ("Pacific Islander", "[[Pacific Islander|Pacific Islander]]"),
    ("[[White (United States Census)|White]]", "[[White (U.S. Census)|White]]"),
    ("[[White (U.S. Census)|White]]", "[[White (U.S. Census)|White]]"),
    ("[[White (U.S. Census)|White]] (NH)", "[[White (U.S. Census)|White]] (NH)"),
    (
        "[[African American (United States Census)|Black or African American]]",
        "[[African Americans|Black or African American]]",
    ),
    (
        "[[African American (U.S. Census)|Black or African American]]",
        "[[African Americans|Black or African American]]",
    ),
    (
        "[[African American (U.S. Census)|Black or African American]] (NH)",
        "[[African Americans|Black or African American]] (NH)",
    ),
    ("[[Native American (United States Census)|Native American]]", "[[Native Americans in the United States|Native American]]"),
    ("[[Native American (U.S. Census)|Native American]]", "[[Native Americans in the United States|Native American]]"),
    ("[[Asian (United States Census)|Asian]]", "[[Asian Americans|Asian]]"),
    ("[[Asian (U.S. Census)|Asian]]", "[[Asian Americans|Asian]]"),
    ("[[Asian (U.S. Census)|Asian]] (NH)", "[[Asian Americans|Asian]] (NH)"),
    ("[[Pacific Islander (United States Census)|Pacific Islander]]", "[[Pacific Islander|Pacific Islander]]"),
    ("[[Pacific Islander (U.S. Census)|Pacific Islander]]", "[[Pacific Islander|Pacific Islander]]"),
    ("[[Race (United States Census)|Other/Mixed]]", "Other/Mixed"),
    ("[[Race (U.S. Census)|Other/Mixed]]", "Other/Mixed"),
    ("[[Hispanic (United States Census)|Hispanic]]", "[[Hispanic and Latino Americans|Hispanic]]"),
    ("[[Hispanic (U.S. Census)|Hispanic]]", "[[Hispanic and Latino Americans|Hispanic]]"),
    ("[[Latino (United States Census)|Latino]]", "[[Hispanic and Latino Americans|Latino]]"),
    ("[[Latino (U.S. Census)|Latino]]", "[[Hispanic and Latino Americans|Latino]]"),
    ("Black or African American", "[[African Americans|Black or African American]]"),
    ("Asian", "[[Asian Americans|Asian]]"),
    ("two or more races", "[[Multiracial Americans|two or more races]]"),
    ("Hispanic or Latino", "[[Hispanic and Latino Americans|Hispanic or Latino]]"),
    ("group quarters", "[[Group quarters|group quarters]]"),
]


def _format_int(value: Optional[int]) -> Optional[str]:
    return f"{value:,}" if value is not None else None


def _format_percent(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    if abs(value) < 0.05:
        return "&lt;0.1%"
    return f"{value:.1f}%"


def _join_phrases(parts: List[str]) -> str:
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def _apply_links(text: str) -> str:
    for phrase, replacement in LINK_REPLACEMENTS:
        if "[[" in phrase:
            text = text.replace(phrase, replacement)
            continue
        pattern = re.compile(r"(?<!\[\[)" + re.escape(phrase) + r"(?![^\[]*\]\])")
        text = pattern.sub(replacement, text)
    return text


def _ensure_template_closed(template: str) -> str:
    """
    Normalize cite templates to be wrapped with exactly '{{' and '}}'.
    """
    trimmed = template.strip()
    while trimmed.startswith("{"):
        trimmed = trimmed[1:]
    while trimmed.endswith("}"):
        trimmed = trimmed[:-1]
    trimmed = trimmed.strip()
    return "{{" + trimmed + "}}"


def _build_citation(
    keys: Set[str],
    seen_sources: Set[str],
    source_urls: Dict[str, Optional[str]],
    force_full: bool = False,
    extra_sources: Optional[Set[str]] = None,
) -> str:
    sources: Set[str] = set()
    if extra_sources:
        sources.update(extra_sources)
    for key in keys:
        sources.update(CITATION_SOURCES.get(key, []))
    if not sources:
        return ""
    parts: List[str] = []
    for source in sorted(sources):
        detail = CITATION_DETAILS[source]
        ref_name = detail["name"]
        first_use = source not in seen_sources
        seen_sources.add(source)

        if force_full and first_use:
            url = source_urls.get(source) or detail["default_url"]
            template = _ensure_template_closed(
                detail["template"].format(url=url, access_date=ACCESS_DATE)
            )
            parts.append(f'<ref name="{ref_name}">{template}</ref>')
        else:
            parts.append(f'<ref name="{ref_name}"/>')
    return "".join(parts)


def _build_paragraph_one(data: Dict[str, object]) -> List[Tuple[str, Set[str]]]:
    sentences: List[Tuple[str, Set[str]]] = []

    total_population = _format_int(data.get("total_population"))
    if total_population:
        sentences.append(
            (
                f"As of the 2020 United States census, the county had a population of {total_population}.",
                {"total_population"},
            )
        )

    under_18 = _format_percent(data.get("age_under_18_percent"))
    over_65 = _format_percent(data.get("age_65_plus_percent"))
    median_age = data.get("age_median_years")
    if median_age is not None or under_18 or over_65:
        parts = []
        keys: Set[str] = set()
        if median_age is not None:
            parts.append(f"The median age was {median_age:.1f} years.")
            keys.add("age_median_years")
        age_details = []
        if under_18:
            age_details.append(f"{under_18} of residents were under the age of 18")
            keys.add("age_under_18_percent")
        if over_65:
            age_details.append(f"{over_65} of residents were 65 years of age or older")
            keys.add("age_65_plus_percent")
        if age_details:
            parts.append(" and ".join(age_details) + ".")
        if parts:
            sentences.append((" ".join(parts), keys))

    sex_ratio = data.get("sex_ratio_males_per_100_females")
    sex_ratio_18 = data.get("sex_ratio_18_plus_males_per_100_females")
    if sex_ratio is not None and sex_ratio_18 is not None:
        sentences.append(
            (
                f"For every 100 females there were {sex_ratio:.1f} males, "
                f"and for every 100 females age 18 and over there were {sex_ratio_18:.1f} males age 18 and over.",
                {"sex_ratio_males_per_100_females", "sex_ratio_18_plus_males_per_100_females"},
            )
        )
    elif sex_ratio is not None:
        sentences.append(
            (
                f"For every 100 females there were {sex_ratio:.1f} males.",
                {"sex_ratio_males_per_100_females"},
            )
        )
    elif sex_ratio_18 is not None:
        sentences.append(
            (
                f"For every 100 females age 18 and over there were {sex_ratio_18:.1f} males.",
                {"sex_ratio_18_plus_males_per_100_females"},
            )
        )

    return sentences


def _build_paragraph_two(data: Dict[str, object]) -> List[Tuple[str, Set[str]]]:
    sentences: List[Tuple[str, Set[str]]] = []

    race_items = []
    race_map = [
        ("race_white_percent", "White"),
        ("race_black_percent", "Black or African American"),
        ("race_aian_percent", "American Indian and Alaska Native"),
        ("race_asian_percent", "Asian"),
        ("race_nhpi_percent", "Native Hawaiian and Pacific Islander"),
        ("race_some_other_percent", "from some other race"),
        ("race_two_or_more_percent", "from two or more races"),
    ]
    for key, label in race_map:
        percent = _format_percent(data.get(key))
        if percent:
            race_items.append(f"{percent} {label}")
    if race_items:
        keys = {
            "race_white_percent",
            "race_black_percent",
            "race_aian_percent",
            "race_asian_percent",
            "race_some_other_percent",
            "race_two_or_more_percent",
        }
        keys = {k for k in keys if data.get(k) is not None}
        sentences.append(
            (
                "The racial makeup of the county was " + _join_phrases(race_items) + ".",
                keys,
            )
        )

    hispanic = _format_percent(data.get("hispanic_any_race_percent"))
    if hispanic:
        sentences.append(
            (
                f"Hispanic or Latino residents of any race comprised {hispanic} of the population.",
                {"hispanic_any_race_percent"},
            )
        )

    return sentences


def _build_paragraph_urbanization(data: Dict[str, object]) -> List[Tuple[str, Set[str]]]:
    sentences: List[Tuple[str, Set[str]]] = []
    urban_pct = _format_percent(data.get("urban_population_percent"))
    rural_pct = _format_percent(data.get("rural_population_percent"))
    if not (urban_pct or rural_pct):
        return sentences

    parts = []
    keys: Set[str] = set()
    if urban_pct:
        parts.append(f"{urban_pct} of residents lived in urban areas")
        keys.add("urban_population_percent")
    if rural_pct:
        parts.append(f"{rural_pct} lived in rural areas")
        keys.add("rural_population_percent")
    if len(parts) == 2:
        sentences.append((f"{parts[0]}, while {parts[1]}.", keys))
    else:
        sentences.append((" and ".join(parts) + ".", keys))
    return sentences


def _build_paragraph_three(data: Dict[str, object]) -> List[Tuple[str, Set[str]]]:
    sentences: List[Tuple[str, Set[str]]] = []

    total_households_val = _format_int(data.get("total_households"))
    if total_households_val:
        clause_parts = []
        keys: Set[str] = {"total_households"}
        children_pct = _format_percent(data.get("households_with_children_under_18_percent"))
        if children_pct:
            clause_parts.append(f"{children_pct} had children under the age of 18 living in them")
            keys.add("households_with_children_under_18_percent")
        clause_text = ", of which " + _join_phrases(clause_parts) if clause_parts else ""
        sentences.append(
            (f"There were {total_households_val} households in the county{clause_text}.", keys)
        )

    married_pct = _format_percent(data.get("married_couple_households_percent"))
    male_pct = _format_percent(data.get("male_householder_no_spouse_percent"))
    female_pct = _format_percent(data.get("female_householder_no_spouse_percent"))
    type_parts = []
    type_keys: Set[str] = set()
    if married_pct:
        type_parts.append(f"{married_pct} were married-couple households")
        type_keys.add("married_couple_households_percent")
    if male_pct:
        type_parts.append(
            f"{male_pct} were households with a male householder and no spouse or partner present"
        )
        type_keys.add("male_householder_no_spouse_percent")
    if female_pct:
        type_parts.append(
            f"{female_pct} were households with a female householder and no spouse or partner present"
        )
        type_keys.add("female_householder_no_spouse_percent")
    if type_parts:
        sentences.append((f"Of all households, {_join_phrases(type_parts)}.", type_keys))

    one_person = _format_percent(data.get("one_person_households_percent"))
    living_alone_65 = _format_percent(data.get("living_alone_65_plus_households_percent"))
    if one_person or living_alone_65:
        clause = []
        keys = set()
        if one_person:
            clause.append(f"{one_person} of all households were made up of individuals")
            keys.add("one_person_households_percent")
        if living_alone_65:
            clause.append(
                f"{living_alone_65} had someone living alone who was 65 years of age or older"
            )
            keys.add("living_alone_65_plus_households_percent")
        sentences.append(("About " + _join_phrases(clause) + ".", keys))

    avg_household = data.get("average_household_size")
    avg_family = data.get("average_family_size")
    total_families = _format_int(data.get("total_families"))
    size_sentence = ""
    if avg_household is not None and avg_family is not None:
        size_sentence = (
            f"The average household size was {avg_household:.1f}, "
            f"and the average family size was {avg_family:.1f}"
        )
    elif avg_household is not None:
        size_sentence = f"The average household size was {avg_household:.1f}"
    elif avg_family is not None:
        size_sentence = f"The average family size was {avg_family:.1f}"

    families_sentence = (
        f"there were {total_families} families residing in the county"
        if total_families
        else ""
    )

    if size_sentence and families_sentence:
        key_set: Set[str] = set()
        if avg_household is not None:
            key_set.add("average_household_size")
        if avg_family is not None:
            key_set.add("average_family_size")
        key_set.add("total_families")
        sentences.append((size_sentence + "; " + families_sentence + ".", key_set))
    elif size_sentence:
        key_set = set()
        if avg_household is not None:
            key_set.add("average_household_size")
        if avg_family is not None:
            key_set.add("average_family_size")
        sentences.append((size_sentence + ".", key_set))
    elif families_sentence:
        sentences.append((families_sentence.capitalize() + ".", {"total_families"}))

    return sentences


def _build_paragraph_four(data: Dict[str, object]) -> List[Tuple[str, Set[str]]]:
    sentences: List[Tuple[str, Set[str]]] = []

    total_housing_units = _format_int(data.get("total_housing_units"))
    vacant_pct = _format_percent(data.get("vacant_units_percent"))
    if total_housing_units:
        clause = ""
        if vacant_pct:
            clause = f", of which {vacant_pct} were vacant"
        keys = {"total_housing_units"}
        if vacant_pct:
            keys.add("vacant_units_percent")
        sentences.append((f"There were {total_housing_units} housing units{clause}.", keys))

    owner_pct = _format_percent(data.get("owner_occupied_percent"))
    renter_pct = _format_percent(data.get("renter_occupied_percent"))
    if owner_pct or renter_pct:
        parts = []
        keys = set()
        if owner_pct:
            parts.append(f"{owner_pct} were owner-occupied")
            keys.add("owner_occupied_percent")
        if renter_pct:
            parts.append(f"{renter_pct} were renter-occupied")
            keys.add("renter_occupied_percent")
        sentences.append(("Among occupied housing units, " + _join_phrases(parts) + ".", keys))

    homeowner_vac = _format_percent(data.get("homeowner_vacancy_rate_percent"))
    rental_vac = _format_percent(data.get("rental_vacancy_rate_percent"))
    vac_parts = []
    if homeowner_vac:
        vac_parts.append(f"The homeowner vacancy rate was {homeowner_vac}")
        keys.add("homeowner_vacancy_rate_percent")
    if rental_vac:
        prefix = "the" if homeowner_vac else "The"
        vac_parts.append(f"{prefix} rental vacancy rate was {rental_vac}")
        keys.add("rental_vacancy_rate_percent")
    if vac_parts:
        sentences.append((" and ".join(vac_parts) + ".", keys))

    return sentences


def generate_county_paragraphs(
    state_fips: str, county_fips: str, full_first_paragraph_refs: bool = False
) -> str:
    """
    Fetch census variables for the given county and return formatted paragraphs.
    """
    data = get_demographic_variables(state_fips, county_fips)
    source_urls = {
        "dp": data.get("_dp_source_url"),
        "pl": data.get("_pl_source_url"),
        "dhc": data.get("_dhc_source_url"),
    }
    paragraph_builders = [
        _build_paragraph_one(data),
        _build_paragraph_two(data),
        _build_paragraph_urbanization(data),
        _build_paragraph_three(data),
        _build_paragraph_four(data),
    ]
    seen_sources: Set[str] = set()
    paragraphs: List[str] = []
    for index, builder in enumerate(paragraph_builders):
        if not builder:
            continue
        sentences_only: List[str] = []
        paragraph_keys: Set[str] = set()
        for sentence, keys in builder:
            sentences_only.append(sentence)
            paragraph_keys.update(keys)
        paragraph_text = " ".join(sentences_only)
        paragraph_text = _apply_links(paragraph_text)
        # When --full-first-refs is set, emit full citations for all paragraphs
        # (ensures DHC in the urban/rural paragraph is fully expanded).
        use_full = full_first_paragraph_refs or index == 0
        extra_sources: Optional[Set[str]] = {"pl", "dp"} if index == 0 else None
        citation = _build_citation(
            paragraph_keys,
            seen_sources,
            source_urls,
            force_full=use_full,
            extra_sources=extra_sources,
        )
        paragraphs.append(paragraph_text + citation)
    body = "\n\n".join(paragraphs)
    if body:
        return "===2020 census===\n\n" + body
    return "===2020 census==="


def main():
    import argparse

    class ExampleArgumentParser(argparse.ArgumentParser):
        def error(self, message):
            example = "Example: python county/generate_county_paragraphs.py 40 029\n"
            self.print_usage(sys.stderr)
            self.exit(2, f"{self.prog}: error: {message}\n{example}")

    parser = ExampleArgumentParser(
        description="Generate county census paragraphs.",
        epilog="Usage: python county/generate_county_paragraphs.py <state_fips> <county_fips>\n"
        "Example: python county/generate_county_paragraphs.py 40 029",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("state_fips")
    parser.add_argument("county_fips")
    parser.add_argument(
        "--full-first-refs",
        action="store_true",
        help="Output full citations for the first paragraph (default: short refs).",
    )
    args = parser.parse_args()
    print(
        generate_county_paragraphs(
            args.state_fips, args.county_fips, full_first_paragraph_refs=args.full_first_refs
        )
    )


if __name__ == "__main__":
    main()
