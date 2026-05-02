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

    def test_restores_lost_links_from_original(self):
        original = """==Demographics==
As of the [[2020 United States census|2020 census]], the [[population density]] was recorded.
"""
        updated = """==Demographics==
As of the 2020 census, the population density was recorded.
"""
        fixed = fix_demographics_section_in_article(
            updated, original_demographics_wikitext=original
        )
        self.assertIn("[[population density]]", fixed)
        self.assertIn("[[2020 United States census|2020 census]]", fixed)

    def test_normalizes_ref_citation_braces_in_demographics(self):
        article = """==Demographics==
Population data<ref>{Cite web|title=Test}</ref>
"""
        fixed = fix_demographics_section_in_article(article)
        self.assertIn("<ref>{{Cite web|title=Test}}</ref>", fixed)

    def test_strips_whitespace_before_citation_refs_in_demographics(self):
        article = """==Demographics==
Population data  
<ref>{{Cite web|title=Test}}</ref>
"""
        fixed = fix_demographics_section_in_article(article)
        self.assertIn("Population data<ref>{{Cite web|title=Test}}</ref>", fixed)

    def test_collapses_extra_newlines_only_in_demographics(self):
        article = """==Demographics==
Line1


Line2
==History==


History text"""
        fixed = fix_demographics_section_in_article(article)
        self.assertIn("Line1\n\nLine2", fixed)
        self.assertIn("==History==\n\n\nHistory text", fixed)

    def test_moves_refs_after_h3_heading_into_first_paragraph(self):
        article = """==Demographics==
===2020 census===<ref name="a"/>
First sentence.

Second paragraph.
==Economy==
Content"""
        fixed = fix_demographics_section_in_article(article)
        self.assertIn("First sentence.<ref name=\"a\"/>", fixed)
        self.assertIn("===2020 census===", fixed)
        # History/Economy section formatting preserved
        self.assertIn("==Economy==\nContent", fixed)

    def test_restores_census_query_params_for_municipality_first_full_ref(self):
        article = """==Demographics==
===2020 census===
As of the [[2020 United States census|2020 census]], Hoot Owl had a population of 0.<ref name="Census2020DP">{{cite web|title=2020 Decennial Census Demographic Profile (DP1)|url=https://api.census.gov/data/2020/dec/dp|website=United States Census Bureau|year=2021|access-date=April 25, 2026|df=mdy}}</ref><ref name="Census2020PL"/>
"""
        fixed = fix_demographics_section_in_article(
            article,
            state_fips="40",
            place_fips="36020",
        )
        self.assertIn("url=https://api.census.gov/data/2020/dec/dp?get=", fixed)
        self.assertIn("&for=place%3A36020&in=state%3A40", fixed)
        self.assertIn('<ref name="Census2020PL">{{cite web|title=2020 Decennial Census Redistricting Data (Public Law 94-171)|url=https://api.census.gov/data/2020/dec/pl?get=', fixed)

    def test_collapses_duplicate_full_census2020pl_defs_in_demographics(self):
        article = """==Demographics==
===2020 census===
As of the [[2020 United States census|2020 census]], Hoot Owl had a population of 0.<ref name="Census2020PL"/>

{| class="wikitable"
|+ Racial composition as of the 2020 census<ref name="Census2020PL">{{cite web|title=2020 Decennial Census Redistricting Data (Public Law 94-171)|url=https://api.census.gov/data/2020/dec/pl?get=NAME%2CP1_001N&for=place%3A36020&in=state%3A40|website=United States Census Bureau|year=2021|access-date=April 25, 2026|df=mdy}}</ref>
|}"""
        fixed = fix_demographics_section_in_article(article)
        self.assertEqual(fixed.count('<ref name="Census2020PL">{{cite web|'), 1)
        self.assertIn('As of the [[2020 United States census|2020 census]], Hoot Owl had a population of 0.<ref name="Census2020PL">{{cite web|', fixed)
        self.assertIn('|+ Racial composition as of the 2020 census<ref name="Census2020PL"/>', fixed)

    def test_preserves_sections_with_heading_comments_after_demographics_fix(self):
        article = """==Demographics==
Population data  
<ref>{{Cite web|title=Test}}</ref>
==Parks and recreation==<!--consensus reached to standardize this heading per WP:WikiProject Cities/US Guideline -->
Park text
==References==
Ref text
"""
        fixed = fix_demographics_section_in_article(article)
        self.assertIn("Population data<ref>{{Cite web|title=Test}}</ref>", fixed)
        self.assertIn("==Parks and recreation==\nPark text", fixed)
        self.assertIn("==References==\nRef text", fixed)


if __name__ == "__main__":
    unittest.main()
