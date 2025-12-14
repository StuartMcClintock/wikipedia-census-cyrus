import unittest

from parser.parser_utils import (
    fix_us_census_population_align,
    fix_census_section_order,
    restore_wikilinks_from_original,
    enforce_ref_citation_template_braces,
    collapse_extra_newlines,
    expand_first_census_refs,
    move_heading_refs_to_first_paragraph,
    strip_whitespace_before_citation_refs,
    strip_whitespace_before_refs,
)


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


class RestoreWikilinksFromOriginalTests(unittest.TestCase):
    def test_restores_missing_links(self):
        original = "The [[population density]] was recorded."
        updated = "The population density was recorded."
        fixed = restore_wikilinks_from_original(original, updated)
        self.assertIn("[[population density]]", fixed)


class StripWhitespaceBeforeRefsTests(unittest.TestCase):
    def test_strips_spaces(self):
        wikitext = "Text  <ref>cite</ref>"
        self.assertEqual(strip_whitespace_before_refs(wikitext), "Text<ref>cite</ref>")

    def test_strips_newlines(self):
        wikitext = "Text\n<ref>cite</ref>"
        self.assertEqual(strip_whitespace_before_refs(wikitext), "Text<ref>cite</ref>")


class ExpandFirstCensusRefsTests(unittest.TestCase):
    def test_expands_first_when_no_full_ref_exists(self):
        wikitext = 'Text <ref name="Census2020PL"/> more <ref name="Census2020PL"/>'
        fixed = expand_first_census_refs(wikitext)
        self.assertIn('<ref name="Census2020PL">{{cite web|', fixed)
        self.assertIn('<ref name="Census2020PL"/>', fixed)

    def test_leaves_short_refs_when_full_already_present(self):
        wikitext = '<ref name="Census2020DP">{{cite web|title=Existing}}</ref> text <ref name="Census2020DP"/>'
        fixed = expand_first_census_refs(wikitext)
        self.assertIn('<ref name="Census2020DP">{{cite web|title=2020 Decennial Census Demographic Profile (DP1)', fixed)
        self.assertNotIn("Existing", fixed)

    def test_overwrites_short_when_full_url_present_elsewhere(self):
        full = '<ref name="Census2020DHC">{{cite web|title=2020 Decennial Census Demographic and Housing Characteristics (DHC)|url=https://api.census.gov/data/2020/dec/dhc?get=NAME%2CP2_002N%2CP2_003N&for=county%3A001&in=state%3A32|website=United States Census Bureau|year=2023|access-date=13 December 2025|df=mdy}}</ref>'
        wikitext = f'Text <ref name="Census2020DHC"/> more {full}'
        fixed = expand_first_census_refs(wikitext)
        self.assertIn(full, fixed)

    def test_overwrites_partial_body_without_full_url(self):
        partial = '<ref name="Census2020DHC">{{cite web|title=2020 Decennial Census Demographic and Housing Characteristics (DHC)|url=https://api.census.gov/data/2020/dec/dhc|website=United States Census Bureau|year=2023|access-date=13 December 2025|df=mdy}}</ref>'
        wikitext = f"Start {partial} then <ref name=\"Census2020DHC\"/>"
        fixed = expand_first_census_refs(wikitext)
        self.assertIn('<ref name="Census2020DHC">{{cite web|title=2020 Decennial Census Demographic and Housing Characteristics (DHC)', fixed)


class EnforceRefCitationTemplateBracesTests(unittest.TestCase):
    def test_normalizes_missing_opening_brace(self):
        wikitext = "<ref>{Cite web|title=Test}</ref>"
        fixed = enforce_ref_citation_template_braces(wikitext)
        self.assertEqual(fixed, "<ref>{{Cite web|title=Test}}</ref>")

    def test_normalizes_missing_closing_brace(self):
        wikitext = "<ref>{{Cite web|title=Test}</ref>"
        fixed = enforce_ref_citation_template_braces(wikitext)
        self.assertEqual(fixed, "<ref>{{Cite web|title=Test}}</ref>")

    def test_normalizes_extra_braces(self):
        wikitext = "<ref>{{{Cite web|title=Test}}}</ref>"
        fixed = enforce_ref_citation_template_braces(wikitext)
        self.assertEqual(fixed, "<ref>{{Cite web|title=Test}}</ref>")

    def test_preserves_plain_text_refs(self):
        wikitext = "<ref>See the 2020 census report.</ref>"
        fixed = enforce_ref_citation_template_braces(wikitext)
        self.assertEqual(fixed, wikitext)

    def test_preserves_nested_template_content(self):
        wikitext = "<ref>{{Cite web|quote={{lang|fr|bonjour}}}}</ref>"
        fixed = enforce_ref_citation_template_braces(wikitext)
        self.assertEqual(fixed, wikitext)

    def test_normalizes_extra_brace_with_nested_template(self):
        wikitext = "<ref>{{Cite web|quote={{lang|fr|bonjour}}}}}</ref>"
        fixed = enforce_ref_citation_template_braces(wikitext)
        self.assertEqual(fixed, "<ref>{{Cite web|quote={{lang|fr|bonjour}}}}</ref>")

    def test_normalizes_single_open_brace_citation(self):
        wikitext = "<ref>{Cite web|title=Test|year=2024}}</ref>"
        fixed = enforce_ref_citation_template_braces(wikitext)
        self.assertEqual(fixed, "<ref>{{Cite web|title=Test|year=2024}}</ref>")

    def test_normalizes_triple_close_brace_single_open_brace_citation(self):
        wikitext = "<ref>{Cite web|title=Test|year=2024}}}</ref>"
        fixed = enforce_ref_citation_template_braces(wikitext)
        self.assertEqual(fixed, "<ref>{{Cite web|title=Test|year=2024}}</ref>")

    def test_normalizes_triple_close_brace_citation(self):
        wikitext = "<ref>{{Cite web|title=Test|year=2024}}}</ref>"
        fixed = enforce_ref_citation_template_braces(wikitext)
        self.assertEqual(fixed, "<ref>{{Cite web|title=Test|year=2024}}</ref>")


class StripWhitespaceBeforeCitationRefsTests(unittest.TestCase):
    def test_removes_spaces_before_citation_ref(self):
        wikitext = "Text   <ref>{{Cite web|title=Test}}</ref>"
        fixed = strip_whitespace_before_citation_refs(wikitext)
        self.assertEqual(fixed, "Text<ref>{{Cite web|title=Test}}</ref>")

    def test_removes_newline_before_citation_ref(self):
        wikitext = "Text.\n    <ref>{{Cite web|title=Test}}</ref>"
        fixed = strip_whitespace_before_citation_refs(wikitext)
        self.assertEqual(fixed, "Text.<ref>{{Cite web|title=Test}}</ref>")

    def test_removes_tab_before_citation_ref(self):
        wikitext = "Text.\t<ref>{{Cite web|title=Test}}</ref>"
        fixed = strip_whitespace_before_citation_refs(wikitext)
        self.assertEqual(fixed, "Text.<ref>{{Cite web|title=Test}}</ref>")

    def test_does_not_touch_plain_ref(self):
        wikitext = "Text   <ref>See note</ref>"
        fixed = strip_whitespace_before_citation_refs(wikitext)
        self.assertEqual(fixed, wikitext)

    def test_skips_when_no_preceding_text(self):
        wikitext = "   <ref>{{Cite web|title=Test}}</ref>"
        fixed = strip_whitespace_before_citation_refs(wikitext)
        self.assertEqual(fixed, wikitext)


class CollapseExtraNewlinesTests(unittest.TestCase):
    def test_collapses_three_newlines(self):
        wikitext = "Line1\n\n\nLine2"
        self.assertEqual(collapse_extra_newlines(wikitext), "Line1\n\nLine2")

    def test_leaves_two_newlines(self):
        wikitext = "Line1\n\nLine2"
        self.assertEqual(collapse_extra_newlines(wikitext), wikitext)

    def test_collapses_long_runs(self):
        wikitext = "A\n\n\n\n\nB"
        self.assertEqual(collapse_extra_newlines(wikitext), "A\n\nB")


class MoveHeadingRefsToFirstParagraphTests(unittest.TestCase):
    def test_moves_ref_into_first_paragraph(self):
        wikitext = """===2020 census===
<ref name="a"/>As of 2020, text.

Second paragraph."""
        fixed = move_heading_refs_to_first_paragraph(wikitext)
        self.assertIn("As of 2020, text.<ref name=\"a\"/>", fixed)
        self.assertIn("Second paragraph.", fixed)

    def test_handles_refs_inline_with_heading(self):
        wikitext = """===2010 census===<ref name="b"/>Start text."""
        fixed = move_heading_refs_to_first_paragraph(wikitext)
        self.assertEqual(fixed, "===2010 census===Start text.<ref name=\"b\"/>")

    def test_leaves_block_when_no_paragraph(self):
        wikitext = """===2000 census===
<ref name="c"/>"""
        self.assertEqual(
            move_heading_refs_to_first_paragraph(wikitext),
            wikitext,
        )


if __name__ == "__main__":
    unittest.main()
