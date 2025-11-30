import unittest

from parser.parser_utils import fix_us_census_population_align


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


if __name__ == "__main__":
    unittest.main()
