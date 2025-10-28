import copy
import unittest
from pathlib import Path

from parser import ParsedWikitext

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
        self.parsed = ParsedWikitext.from_wikitext(self.wikitext)
        self.original_sections = copy.deepcopy(self.parsed.sections)

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
        reparsed = ParsedWikitext.from_wikitext(reconstructed).sections
        self.assertEqual(reparsed, self.original_sections)
        self.assertIn("==History==", reconstructed)
        self.assertIn("==Geography==", reconstructed)
        self.assertNotIn("== Geography ==", reconstructed)

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


if __name__ == "__main__":
    unittest.main()
