import re
import unittest
from copy import deepcopy
from unittest.mock import patch

from municipality.generate_municipality_paragraphs import generate_municipality_paragraphs


class GenerateMunicipalityParagraphsSmallCountsTests(unittest.TestCase):
    def setUp(self):
        self.base_data = {
            "place_name": "Testville",
            "_dp_source_url": "dp",
            "_pl_source_url": "pl",
            "_dhc_source_url": "dhc",
        }

    def test_single_household_and_small_housing_units(self):
        data = deepcopy(self.base_data)
        data.update(
            {
                "place_name": "Greenhorn",
                "total_households": 1,
                "households_with_children_under_18_percent": 100.0,
                "married_couple_households_percent": 100.0,
                "male_householder_no_spouse_percent": 0.0,
                "female_householder_no_spouse_percent": 0.0,
                "one_person_households_percent": 0.0,
                "living_alone_65_plus_households_percent": 0.0,
                "total_housing_units": 3,
                "vacant_units_percent": 66.7,
                "vacant_units_count": 2,
                "owner_occupied_percent": 100.0,
                "renter_occupied_percent": 0.0,
            }
        )
        with patch(
            "municipality.generate_municipality_paragraphs.get_demographic_variables",
            return_value=data,
        ):
            text = self._strip_refs(generate_municipality_paragraphs("40", "55150"))

        self.assertIn(
            "Greenhorn had 1 household, and it included children under the age of 18.",
            text,
        )
        self.assertIn("The household was a married couple.", text)
        self.assertIn(
            "There were no households headed by a single male or single female householder.",
            text,
        )
        self.assertIn(
            "There were no one-person households, including anyone living alone who was 65 years of age or older.",
            text,
        )
        self.assertIn("There were 3 housing units, and 2 were vacant (66.7%).", text)
        self.assertIn("The single occupied housing unit was owner-occupied.", text)
        self.assertIn("There were no renter-occupied units.", text)

    def test_two_households_use_count_based_phrasing(self):
        data = deepcopy(self.base_data)
        data.update(
            {
                "place_name": "Tinyville",
                "total_households": 2,
                "households_with_children_under_18_percent": 50.0,
                "married_couple_households_percent": 50.0,
                "male_householder_no_spouse_percent": 0.0,
                "female_householder_no_spouse_percent": 50.0,
                "one_person_households_percent": 50.0,
                "living_alone_65_plus_households_percent": 0.0,
            }
        )
        with patch(
            "municipality.generate_municipality_paragraphs.get_demographic_variables",
            return_value=data,
        ):
            text = self._strip_refs(generate_municipality_paragraphs("12", "001"))

        self.assertIn("There were 2 households in Tinyville.", text)
        self.assertIn("One of the two households had children under the age of 18.", text)
        self.assertIn(
            "One of the two households was a married-couple household.",
            text,
        )
        self.assertIn(
            "One of the two households had a female householder and no spouse or partner present.",
            text,
        )
        self.assertIn("One of the two households was made up of individuals.", text)

    def test_single_housing_unit_renter_only(self):
        data = deepcopy(self.base_data)
        data.update(
            {
                "place_name": "Minicove",
                "total_housing_units": 1,
                "vacant_units_percent": 0.0,
                "vacant_units_count": 0,
                "owner_occupied_percent": 0.0,
                "renter_occupied_percent": 100.0,
            }
        )
        with patch(
            "municipality.generate_municipality_paragraphs.get_demographic_variables",
            return_value=data,
        ):
            text = self._strip_refs(generate_municipality_paragraphs("01", "002"))

        self.assertIn("There was 1 housing unit, and none were vacant (0%).", text)
        self.assertIn("The single occupied housing unit was renter-occupied.", text)
        self.assertIn("There were no owner-occupied units.", text)

    def test_three_households_use_specific_counts(self):
        data = deepcopy(self.base_data)
        data.update(
            {
                "place_name": "Smallville",
                "total_households": 3,
                "households_with_children_under_18_percent": 33.3,
                "one_person_households_percent": 66.7,
                "living_alone_65_plus_households_percent": 33.3,
            }
        )
        with patch(
            "municipality.generate_municipality_paragraphs.get_demographic_variables",
            return_value=data,
        ):
            text = self._strip_refs(generate_municipality_paragraphs("20", "12345"))

        self.assertIn(
            "One of the three households had children under the age of 18.",
            text,
        )
        self.assertIn(
            "Two of the three households were made up of individuals.",
            text,
        )
        self.assertIn(
            "One of the three households had someone living alone who was 65 years of age or older.",
            text,
        )

    @staticmethod
    def _strip_refs(text: str) -> str:
        return re.sub(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", "", text, flags=re.DOTALL)


if __name__ == "__main__":
    unittest.main()
