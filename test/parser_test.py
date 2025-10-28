import copy
import unittest
from pathlib import Path

from parser import (
    parse_wikitext_sections,
    get_article_outline,
    unparse_wikitext_sections,
    overwrite_wikitext_section,
)

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

    def test_unparse_round_trip_matches_original_structure(self):
        reconstructed = unparse_wikitext_sections(self.sections)
        reparsed = parse_wikitext_sections(reconstructed)
        self.assertEqual(reparsed, self.sections)

    def test_overwrite_wikitext_section_updates_leaf_content(self):
        sections_copy = copy.deepcopy(self.sections)
        new_text = "new geography content"
        overwrite_wikitext_section(sections_copy, ["Geography", "__content__"], new_text)
        geography_entry = next(item for item in sections_copy if item[0] == "Geography")
        content_entry = next(item for item in geography_entry[1] if item[0] == "__content__")
        self.assertEqual(content_entry[1], new_text)

    def test_overwrite_wikitext_section_raises_for_missing_path(self):
        sections_copy = copy.deepcopy(self.sections)
        with self.assertRaises(KeyError):
            overwrite_wikitext_section(sections_copy, ["NotASection"], "text")

    def test_overwrite_wikitext_section_requires_leaf_section(self):
        sections_copy = copy.deepcopy(self.sections)
        with self.assertRaises(ValueError):
            overwrite_wikitext_section(sections_copy, ["Geography"], "text")

    def test_overwrite_wikitext_section_raises_when_path_too_deep(self):
        sections_copy = copy.deepcopy(self.sections)
        with self.assertRaises(ValueError):
            overwrite_wikitext_section(
                sections_copy,
                ["Geography", "__content__", "Extra"],
                "text",
            )


if __name__ == "__main__":
    unittest.main()
