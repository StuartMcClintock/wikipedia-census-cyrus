import unittest
from pathlib import Path

from parser import parse_wikitext_sections, get_article_outline

COAL_COUNTY_EXPECTED_OUTLINE = '''Coal County, Oklahoma
  __lead__
  History
  Geography
    __content__
    Major highways
    Adjacent counties
  Demographics
  Politics
  Communities
    Cities
    Towns
    Census-designated places
    Other unincorporated communities
  NRHP sites
  References
  External links'''


class PrintArticleOutlineTests(unittest.TestCase):
    def setUp(self):
        fixture_path = Path(__file__).with_name("Coal_County_test_data.txt")
        self.wikitext = fixture_path.read_text(encoding="utf-8")
        self.sections = parse_wikitext_sections(self.wikitext)

    def test_outline_matches_expected_fixture(self):
        outline = get_article_outline("Coal County, Oklahoma", self.sections)
        self.assertEqual(outline, COAL_COUNTY_EXPECTED_OUTLINE)

    def test_outline_returns_title_when_no_sections(self):
        self.assertEqual(
            get_article_outline("Empty Article", []),
            "Empty Article",
        )


if __name__ == "__main__":
    unittest.main()
