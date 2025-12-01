import unittest

from parser.parser_utils import fix_us_census_population_align
from parser.parser_utils import fix_census_section_order


class FixUSCensusPopulationAlignTests(unittest.TestCase):
    def test_updates_align_to_right(self):
        wikitext = """Intro
{{US Census population
| 1920 = 100
| align = center
| align-fn = center
}}
Footer"""

        result = fix_us_census_population_align(wikitext)

        self.assertIn("| align = right", result)
        self.assertNotIn("| align = center", result)
        self.assertIn("| align-fn = center", result)

    def test_adds_align_fn_when_missing(self):
        wikitext = """{{US Census population
| 2020 = 2467
| align = left
}}"""

        result = fix_us_census_population_align(wikitext)

        self.assertIn("| align = right", result)
        self.assertIn("| align-fn = center", result)

    def test_adds_align_and_align_fn_when_missing(self):
        wikitext = """{{US Census population
| 2020 = 2467
}}"""

        result = fix_us_census_population_align(wikitext)

        self.assertIn("| align = right", result)
        self.assertIn("| align-fn = center", result)

    def test_align_already_right_adds_align_fn(self):
        wikitext = """{{US Census population
| 2020 = 2467
| align = right
}}"""

        result = fix_us_census_population_align(wikitext)

        self.assertIn("| align = right", result)
        self.assertIn("| align-fn = center", result)


class FixCensusSectionOrderTests(unittest.TestCase):
    def test_reorders_census_sections(self):
        wikitext = """Lead text
===2010 census===
2010 data
===2020 census===
2020 data
===2000 census===
2000 data
===Economy===
Other text
"""

        fixed = fix_census_section_order(wikitext)

        expected = """Lead text
===2020 census===
2020 data
===2010 census===
2010 data
===2000 census===
2000 data
===Economy===
Other text
"""
        self.assertEqual(fixed, expected)


if __name__ == "__main__":
    unittest.main()
