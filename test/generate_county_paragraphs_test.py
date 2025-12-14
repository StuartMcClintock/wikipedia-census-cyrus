import re
import unittest
from copy import deepcopy
from unittest.mock import patch

from county.generate_county_paragraphs import (
    _ensure_template_closed,
    _apply_links,
    generate_county_paragraphs,
)


class GenerateCountyParagraphsTests(unittest.TestCase):
    def setUp(self):
        self.full_data = {
            "total_population": 12345,
            "total_households": 4321,
            "total_families": 3000,
            "total_housing_units": 5000,
            "race_white_percent": 60.0,
            "race_black_percent": 20.0,
            "race_aian_percent": 5.0,
            "race_asian_percent": 10.0,
            "race_nhpi_percent": 1.0,
            "race_some_other_percent": 3.0,
            "race_two_or_more_percent": 2.0,
            "hispanic_any_race_percent": 8.5,
            "households_with_children_under_18_percent": 35.0,
            "married_couple_households_percent": 50.0,
            "female_householder_no_spouse_percent": 15.0,
            "one_person_households_percent": 25.0,
            "living_alone_65_plus_households_percent": 10.0,
            "average_household_size": 2.5,
            "average_family_size": 3.1,
            "age_under_18_percent": 22.3,
            "age_65_plus_percent": 15.4,
            "age_median_years": 38.5,
            "sex_ratio_males_per_100_females": 96.7,
            "sex_ratio_18_plus_males_per_100_females": 94.2,
            "owner_occupied_percent": 65.1,
            "renter_occupied_percent": 34.9,
            "vacant_units_percent": 8.2,
            "homeowner_vacancy_rate_percent": 1.5,
            "rental_vacancy_rate_percent": 5.4,
            "group_quarters_percent": 2.1,
            "institutional_group_quarters_percent": 1.0,
            "noninstitutional_group_quarters_percent": 1.1,
        }
        self.mock_dp_url = (
            "https://api.census.gov/data/2020/dec/dp?"
            "get=mock&for=county%3A029&in=state%3A40"
        )
        self.mock_pl_url = (
            "https://api.census.gov/data/2020/dec/pl?"
            "get=mock&for=county%3A029&in=state%3A40"
        )
        self.full_data["_dp_source_url"] = self.mock_dp_url
        self.full_data["_pl_source_url"] = self.mock_pl_url

    def test_generate_paragraphs_with_full_data(self):
        expected_paragraphs = [
            (
                "As of the [[2020 United States census|2020 census]], the county had a population of 12,345. "
                "The median age was 38.5 years. 22.3% of residents were under the age of 18 and 15.4% of residents were 65 years of age or older. "
                "For every 100 females there were 96.7 males, and for every 100 females age 18 and over there were 94.2 males age 18 and over."
            ),
            (
                "The racial makeup of the county was 60.0% White, 20.0% [[African Americans|Black or African American]], "
                "5.0% [[Native Americans in the United States|American Indian and Alaska Native]], 10.0% [[Asian Americans|Asian]], "
                "1.0% [[Native Hawaiians|Native Hawaiian]] and [[Pacific Islander|Pacific Islander]], 3.0% from some other race, "
                "and 2.0% from [[Multiracial Americans|two or more races]]. "
                "[[Hispanic and Latino Americans|Hispanic or Latino]] residents of any race comprised 8.5% of the population."
            ),
            (
                "There were 4,321 households in the county, of which 35.0% had children under the age of 18 living with them, "
                "50.0% were married-couple households, and 15.0% had a female householder with no spouse or partner present. "
                "About 25.0% of all households were made up of individuals and 10.0% had someone living alone who was 65 years of age or older. "
                "The average household size was 2.5, and the average family size was 3.1; "
                "there were 3,000 families residing in the county."
            ),
            (
                "There were 5,000 housing units, of which 8.2% were vacant. "
                "Among occupied housing units, 65.1% were owner-occupied and 34.9% were renter-occupied. "
                "The homeowner vacancy rate was 1.5% and the rental vacancy rate was 5.4%."
            ),
        ]

        with patch(
            "county.generate_county_paragraphs.get_demographic_variables",
            return_value=deepcopy(self.full_data),
        ):
            text = generate_county_paragraphs("40", "029")

        expected_text = "===2020 census===\n\n" + "\n\n".join(expected_paragraphs)
        self.assertEqual(self._strip_refs(text), expected_text)
        self.assertIn('<ref name="Census2020DP"/>', text)
        self.assertIn('<ref name="Census2020PL"/>', text)

    def test_generate_paragraphs_with_missing_data(self):
        minimal = {key: None for key in self.full_data}
        minimal.update(
            {
                "total_population": 2000,
                "age_65_plus_percent": 12.0,
                "sex_ratio_18_plus_males_per_100_females": 90.0,
                "group_quarters_percent": 3.2,
                "total_households": 800,
                "total_families": 500,
                "total_housing_units": 1000,
                "owner_occupied_percent": 70.0,
                "rental_vacancy_rate_percent": 4.0,
                "_dp_source_url": self.mock_dp_url,
                "_pl_source_url": self.mock_pl_url,
            }
        )

        with patch(
            "county.generate_county_paragraphs.get_demographic_variables",
            return_value=minimal,
        ):
            text = generate_county_paragraphs("20", "001")

        expected_text = "===2020 census===\n\n" + "\n\n".join(
            [
                (
                    "As of the [[2020 United States census|2020 census]], the county had a population of 2,000. "
                    "12.0% of residents were 65 years of age or older. "
                    "For every 100 females age 18 and over there were 90.0 males."
                ),
                "There were 800 households in the county. There were 500 families residing in the county.",
                (
                    "There were 1,000 housing units. "
                    "Among occupied housing units, 70.0% were owner-occupied. "
                    "The rental vacancy rate was 4.0%."
                ),
            ]
        )
        self.assertEqual(self._strip_refs(text), expected_text)
        self.assertNotIn("None", text)

    def test_ensure_template_closed_adds_missing_braces(self):
        template = "{cite web|title=Bad Template|url=URL|access-date=DATE}"
        normalized = _ensure_template_closed(template)
        self.assertEqual(normalized, "{{cite web|title=Bad Template|url=URL|access-date=DATE}}")

    def test_zero_percent_values_render_as_none(self):
        zero_data = deepcopy(self.full_data)
        zero_data.update(
            {
                "group_quarters_percent": 5.5,
                "institutional_group_quarters_percent": 2.0,
                "noninstitutional_group_quarters_percent": 0.0,
                "vacant_units_percent": 0.0,
                "owner_occupied_percent": 0.0,
                "renter_occupied_percent": 100.0,
                "homeowner_vacancy_rate_percent": 0.0,
                "rental_vacancy_rate_percent": 0.0,
            }
        )

        with patch(
            "county.generate_county_paragraphs.get_demographic_variables",
            return_value=zero_data,
        ):
            text = generate_county_paragraphs("12", "005")

        self.assertIn("of which 0.0% were vacant", text)
        self.assertIn(
            "Among occupied housing units, 0.0% were owner-occupied and 100.0% were renter-occupied.",
            text,
        )
        self.assertIn(
            "The homeowner vacancy rate was 0.0% and the rental vacancy rate was 0.0%.",
            text,
        )

    def test_includes_urban_rural_split_when_available(self):
        data = {
            "total_population": 1000,
            "urban_population_percent": 60.0,
            "rural_population_percent": 40.0,
            "total_households": None,
            "total_families": None,
            "total_housing_units": None,
            "_dp_source_url": "dp",
            "_pl_source_url": "pl",
            "_dhc_source_url": "dhc",
        }

        with patch(
            "county.generate_county_paragraphs.get_demographic_variables",
            return_value=data,
        ):
            text = generate_county_paragraphs("50", "003")

        expected = (
            "===2020 census===\n\n"
            "As of the [[2020 United States census|2020 census]], the county had a population of 1,000. "
            "60.0% of residents lived in urban areas, while 40.0% lived in rural areas."
        )
        self.assertEqual(self._strip_refs(text), expected)

    def test_sex_ratio_and_age_read_naturally(self):
        with patch(
            "county.generate_county_paragraphs.get_demographic_variables",
            return_value=deepcopy(self.full_data),
        ):
            text = self._strip_refs(generate_county_paragraphs("40", "029"))

        self.assertIn("The median age was 38.5 years.", text)
        self.assertIn(
            "22.3% of residents were under the age of 18 and 15.4% of residents were 65 years of age or older.",
            text,
        )
        self.assertIn("there were 94.2 males age 18 and over", text)

    def test_no_residents_lived_in_prefix_in_urban_sentence(self):
        data = {
            "total_population": 1000,
            "urban_population_percent": 61.9,
            "rural_population_percent": 38.1,
            "_dp_source_url": "dp",
            "_pl_source_url": "pl",
            "_dhc_source_url": "dhc",
        }
        with patch(
            "county.generate_county_paragraphs.get_demographic_variables",
            return_value=data,
        ):
            text = self._strip_refs(generate_county_paragraphs("12", "003"))

        self.assertNotIn("Residents lived in", text)
        self.assertIn(
            "61.9% of residents lived in urban areas, while 38.1% lived in rural areas.",
            text,
        )

    def test_census_link_replacements(self):
        cases = [
            (
                "[[White (United States Census)|White]] (non-Hispanic)",
                "[[White (U.S. Census)|White]] (non-Hispanic)",
            ),
            (
                "[[White (U.S. Census)|White]] (non-Hispanic)",
                "[[White (U.S. Census)|White]] (non-Hispanic)",
            ),
            (
                "[[African American (United States Census)|Black or African American]]",
                "[[African Americans|Black or African American]]",
            ),
            (
                "[[African American (U.S. Census)|Black or African American]]",
                "[[African Americans|Black or African American]]",
            ),
            (
                "[[Native American (United States Census)|Native American]]",
                "[[Native Americans in the United States|Native American]]",
            ),
            (
                "[[Native American (U.S. Census)|Native American]]",
                "[[Native Americans in the United States|Native American]]",
            ),
            (
                "[[Asian (United States Census)|Asian]]",
                "[[Asian Americans|Asian]]",
            ),
            (
                "[[Asian (U.S. Census)|Asian]]",
                "[[Asian Americans|Asian]]",
            ),
            (
                "[[Pacific Islander (United States Census)|Pacific Islander]]",
                "[[Pacific Islander|Pacific Islander]]",
            ),
            (
                "[[Pacific Islander (U.S. Census)|Pacific Islander]]",
                "[[Pacific Islander|Pacific Islander]]",
            ),
            (
                "[[Race (United States Census)|Other/Mixed]]",
                "Other/Mixed",
            ),
            (
                "[[Race (U.S. Census)|Other/Mixed]]",
                "Other/Mixed",
            ),
            (
                "[[Hispanic (United States Census)|Hispanic]]",
                "[[Hispanic and Latino Americans|Hispanic]]",
            ),
            (
                "[[Hispanic (U.S. Census)|Hispanic]]",
                "[[Hispanic and Latino Americans|Hispanic]]",
            ),
            (
                "[[Latino (United States Census)|Latino]]",
                "[[Hispanic and Latino Americans|Latino]]",
            ),
            (
                "[[Latino (U.S. Census)|Latino]]",
                "[[Hispanic and Latino Americans|Latino]]",
            ),
        ]
        for source, expected in cases:
            self.assertEqual(_apply_links(source), expected)

    @staticmethod
    def _strip_refs(text: str) -> str:
        return re.sub(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", "", text, flags=re.DOTALL)


if __name__ == "__main__":
    unittest.main()
