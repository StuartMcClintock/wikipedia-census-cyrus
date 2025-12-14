import unittest

from census_api.utils import build_census_ref, get_dp_ref, get_pl_ref, get_dhc_ref


class CensusUtilsRefTests(unittest.TestCase):
    def test_dp_ref(self):
        ref = get_dp_ref(access_date="1 January 2025", url="http://example.com/dp")
        self.assertIn('<ref name="Census2020DP">', ref)
        self.assertIn("http://example.com/dp", ref)
        self.assertIn("access-date=1 January 2025", ref)

    def test_pl_ref(self):
        ref = get_pl_ref(access_date="2 February 2025", url="http://example.com/pl")
        self.assertIn('<ref name="Census2020PL">', ref)
        self.assertIn("http://example.com/pl", ref)
        self.assertIn("access-date=2 February 2025", ref)

    def test_dhc_ref(self):
        ref = get_dhc_ref(access_date="3 March 2025", url="http://example.com/dhc")
        self.assertIn('<ref name="Census2020DHC">', ref)
        self.assertIn("http://example.com/dhc", ref)
        self.assertIn("access-date=3 March 2025", ref)

    def test_build_census_ref_handles_braces(self):
        ref = build_census_ref("dp", url="http://example.com", access_date="4 April 2025")
        self.assertTrue(ref.startswith('<ref name="Census2020DP">{{'))
        self.assertTrue(ref.endswith("}}</ref>"))


if __name__ == "__main__":
    unittest.main()
