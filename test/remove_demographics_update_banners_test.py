import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "remove_demographics_update_banners.py"
)
SPEC = importlib.util.spec_from_file_location(
    "remove_demographics_update_banners",
    MODULE_PATH,
)
remove_demographics_update_banners = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(remove_demographics_update_banners)


remove_banner_templates = remove_demographics_update_banners.remove_banner_templates
_iter_articles = remove_demographics_update_banners._iter_articles


class RemoveBannerTemplatesTests(unittest.TestCase):
    def test_removes_matching_banner_when_census_is_mentioned(self):
        wikitext = """Lead
{{Update|date=January 2024|This census data is outdated.}}
Body
"""

        new_text, removed = remove_banner_templates(wikitext)

        self.assertEqual(new_text, "Lead\nBody\n")
        self.assertEqual(removed, ["Update"])

    def test_removes_matching_banner_when_demographic_is_mentioned(self):
        wikitext = """Lead
{{Outdated|date=January 2024|demographic section needs updating}}
Body
"""

        new_text, removed = remove_banner_templates(wikitext)

        self.assertEqual(new_text, "Lead\nBody\n")
        self.assertEqual(removed, ["Outdated"])

    def test_keeps_matching_banner_when_no_required_substring_is_present(self):
        wikitext = """Lead
{{Update|date=January 2024|statistics in this section are outdated.}}
Body
"""

        new_text, removed = remove_banner_templates(wikitext)

        self.assertEqual(new_text, wikitext)
        self.assertEqual(removed, [])


class IterArticlesTests(unittest.TestCase):
    def test_start_at_exact_title_still_works(self):
        titles = {"Albany", "Boston", "Chicago"}

        result = list(_iter_articles(titles, start_at="Boston", limit=None))

        self.assertEqual(result, ["Boston", "Chicago"])

    def test_start_at_skips_to_first_title_after_input_alphabetically(self):
        titles = {"Albany", "Boston", "Chicago"}

        result = list(_iter_articles(titles, start_at="Carson", limit=None))

        self.assertEqual(result, ["Chicago"])

    def test_start_at_accepts_space_form_for_underscored_titles(self):
        titles = {"Alpha_Town", "Boulder_City", "Cedar_Point"}

        result = list(_iter_articles(titles, start_at="Boulder City", limit=None))

        self.assertEqual(result, ["Boulder_City", "Cedar_Point"])


if __name__ == "__main__":
    unittest.main()
