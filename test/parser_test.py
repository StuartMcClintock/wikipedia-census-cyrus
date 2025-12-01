import copy
import unittest
from pathlib import Path

from parser.parser import ParsedWikitext, fix_demographics_section_in_article

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
        self.parsed = ParsedWikitext(wikitext=self.wikitext)
        self.original_sections = copy.deepcopy(self.parsed.sections)
        self.original_length = len(self.wikitext)

    def test_outline_matches_expected_fixture(self):
        outline = self.parsed.outline("Coal County, Oklahoma")
        self.assertEqual(outline, COAL_COUNTY_EXPECTED_OUTLINE)

    def test_outline_returns_title_when_no_sections(self):
        self.assertEqual(
            ParsedWikitext([]).outline("Empty Article"),
            "Empty Article",
        )

    def test_unparse_round_trip_matches_original_structure(self):
        reconstructed = self.parsed.to_wikitext()
        reparsed = ParsedWikitext(wikitext=reconstructed).sections
        self.assertEqual(reparsed, self.original_sections)
        self.assertIn("==History==", reconstructed)
        self.assertIn("==Geography==", reconstructed)
        self.assertNotIn("== Geography ==", reconstructed)

    def test_original_length_recorded(self):
        self.assertEqual(self.parsed.original_length, self.original_length)

    def test_overwrite_wikitext_section_updates_leaf_content(self):
        clone = self.parsed.clone()
        new_text = "new geography content"
        clone.overwrite_section(["Geography", "__content__"], new_text)
        updated_text = clone.get_section(["Geography", "__content__"])
        self.assertEqual(updated_text, new_text)

    def test_overwrite_wikitext_section_raises_for_missing_path(self):
        clone = self.parsed.clone()
        with self.assertRaises(KeyError):
            clone.overwrite_section(["NotASection"], "text")

    def test_overwrite_wikitext_section_requires_leaf_section(self):
        clone = self.parsed.clone()
        with self.assertRaises(ValueError):
            clone.overwrite_section(["Geography"], "text")

    def test_overwrite_wikitext_section_raises_when_path_too_deep(self):
        clone = self.parsed.clone()
        with self.assertRaises(ValueError):
            clone.overwrite_section(["Geography", "__content__", "Extra"], "text")

    def test_get_wikitext_section_returns_expected_content(self):
        text = self.parsed.get_section(["Geography", "__content__"])
        expected_entry = next(item for item in self.original_sections if item[0] == "Geography")
        expected_content = next(item for item in expected_entry[1] if item[0] == "__content__")[1]
        self.assertEqual(text, expected_content)

    def test_get_wikitext_section_raises_for_missing_path(self):
        with self.assertRaises(KeyError):
            self.parsed.get_section(["NotASection"])

    def test_get_wikitext_section_raises_for_subsections(self):
        with self.assertRaises(ValueError):
            self.parsed.get_section(["Geography"])


class FixDemographicsSectionTests(unittest.TestCase):
    def test_align_field_is_normalized(self):
        article = """{{Short description|County}}
==Demographics==
{{US Census population
| 1920 = 100
| align = center
| align-fn = center
}}
==References=="""

        fixed = fix_demographics_section_in_article(article)

        self.assertIn("| align = right", fixed)
        self.assertIn("| align-fn = center", fixed)
        self.assertNotIn("| align = center", fixed)

    def test_noop_when_no_demographics_section(self):
        article = "==History==\nSome text."
        self.assertEqual(
            fix_demographics_section_in_article(article),
            article,
        )

    def test_reorders_census_subsections(self):
        article = """==Demographics==
===2010 census===
2010 data
===2020 census===
2020 data
===2000 census===
2000 data
"""
        fixed = fix_demographics_section_in_article(article)
        self.assertLess(fixed.find("===2020 census==="), fixed.find("===2010 census==="))
        self.assertLess(fixed.find("===2010 census==="), fixed.find("===2000 census==="))


if __name__ == "__main__":
    unittest.main()
