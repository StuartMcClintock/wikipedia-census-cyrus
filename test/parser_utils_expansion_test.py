import unittest

from parser.parser_utils import expand_first_census_refs


class ExpandFirstCensusRefsWithFipsTests(unittest.TestCase):
    def test_uses_full_url_when_no_full_ref_exists(self):
        wikitext = 'Text <ref name="Census2020PL"/>'
        fixed = expand_first_census_refs(
            wikitext,
            state_fips="13",
            county_fips="077",
        )
        self.assertIn("get=NAME", fixed)
        self.assertIn("for=county%3A077", fixed)
        self.assertIn("in=state%3A13", fixed)

    def test_uses_full_url_for_partial_body(self):
        partial = '<ref name="Census2020DP">{{cite web|title=2020 Decennial Census Demographic Profile (DP1)|url=https://api.census.gov/data/2020/dec/dp|website=United States Census Bureau|year=2021|access-date=13 December 2025|df=mdy}}</ref>'
        wikitext = f"Start {partial}"
        fixed = expand_first_census_refs(
            wikitext,
            state_fips="01",
            county_fips="003",
        )
        self.assertIn("for=county%3A003", fixed)
        self.assertIn("in=state%3A01", fixed)
        self.assertIn("get=NAME", fixed)


if __name__ == "__main__":
    unittest.main()
