import unittest

from parser.parser_utils import (
    fix_us_census_population_align,
    fix_census_section_order,
    restore_wikilinks_from_original,
    enforce_ref_citation_template_braces,
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


if __name__ == "__main__":
    unittest.main()
