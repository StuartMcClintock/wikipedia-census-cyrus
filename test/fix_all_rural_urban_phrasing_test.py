import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "fix_all_rural_urban_phrasing"
    / "main.py"
)
SPEC = importlib.util.spec_from_file_location(
    "fix_all_rural_urban_phrasing",
    MODULE_PATH,
)
fix_all_rural_urban_phrasing = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(fix_all_rural_urban_phrasing)


replace_all_rural_urban_phrasing = (
    fix_all_rural_urban_phrasing.replace_all_rural_urban_phrasing
)
replace_all_rural_urban_phrasing_in_demographics_2020 = (
    fix_all_rural_urban_phrasing.replace_all_rural_urban_phrasing_in_demographics_2020
)
_iter_articles = fix_all_rural_urban_phrasing._iter_articles
_format_edits_per_minute = fix_all_rural_urban_phrasing._format_edits_per_minute
_load_flagged_titles = fix_all_rural_urban_phrasing._load_flagged_titles
_write_flagged_titles = fix_all_rural_urban_phrasing._write_flagged_titles


class ReplaceAllRuralUrbanPhrasingTests(unittest.TestCase):
    def test_replaces_all_rural_sentence_and_preserves_refs(self):
        text = (
            "There were 574 housing units. "
            "0.0% of residents lived in urban areas, while 100.0% lived in rural areas."
            "<ref name=\"Census2020DHC\"/>"
        )

        updated, count = replace_all_rural_urban_phrasing(text)

        self.assertEqual(count, 1)
        self.assertIn(
            "All residents lived in rural areas.<ref name=\"Census2020DHC\"/>",
            updated,
        )
        self.assertNotIn("0.0% of residents lived in urban areas", updated)

    def test_replaces_all_urban_sentence(self):
        text = "100.0% of residents lived in urban areas, while 0.0% lived in rural areas."

        updated, count = replace_all_rural_urban_phrasing(text)

        self.assertEqual(count, 1)
        self.assertEqual(updated, "All residents lived in urban areas.")

    def test_replaces_near_zero_all_rural_sentence(self):
        text = (
            "&lt;0.1% of residents lived in urban areas, while 100.0% lived in rural areas."
        )

        updated, count = replace_all_rural_urban_phrasing(text)

        self.assertEqual(count, 1)
        self.assertEqual(updated, "All residents lived in rural areas.")

    def test_replaces_near_zero_all_urban_sentence(self):
        text = "100.0% of residents lived in urban areas, while <0.1% lived in rural areas."

        updated, count = replace_all_rural_urban_phrasing(text)

        self.assertEqual(count, 1)
        self.assertEqual(updated, "All residents lived in urban areas.")

    def test_leaves_mixed_split_untouched(self):
        text = "61.9% of residents lived in urban areas, while 38.1% lived in rural areas."

        updated, count = replace_all_rural_urban_phrasing(text)

        self.assertEqual(count, 0)
        self.assertEqual(updated, text)


class ReplaceInDemographicsSectionTests(unittest.TestCase):
    def test_only_updates_2020_census_inside_demographics(self):
        article = """Lead text.

==Demographics==
===2010 census===
0.0% of residents lived in urban areas, while 100.0% lived in rural areas.

===2020 census===
&lt;0.1% of residents lived in urban areas, while 100.0% lived in rural areas.<ref name="Census2020DHC"/>

==Geography==
100.0% of residents lived in urban areas, while 0.0% lived in rural areas.
"""

        updated, count = replace_all_rural_urban_phrasing_in_demographics_2020(article)

        self.assertEqual(count, 1)
        self.assertIn(
            "All residents lived in rural areas.<ref name=\"Census2020DHC\"/>",
            updated,
        )
        self.assertIn(
            "===2010 census===\n0.0% of residents lived in urban areas, while 100.0% lived in rural areas.",
            updated,
        )
        self.assertIn(
            "==Geography==\n100.0% of residents lived in urban areas, while 0.0% lived in rural areas.",
            updated,
        )


class FlaggedLogTests(unittest.TestCase):
    def test_write_and_load_flagged_titles_round_trip(self):
        with self.subTest("round trip"):
            from tempfile import TemporaryDirectory

            with TemporaryDirectory() as tmpdir:
                log_path = Path(tmpdir) / "flagged_articles.log"
                _write_flagged_titles(
                    ["Alpha_Town", "Beta Town", "Alpha Town"],
                    log_path=log_path,
                )

                loaded = _load_flagged_titles(log_path)

        self.assertEqual(loaded, ["Alpha_Town", "Beta_Town"])

    def test_load_flagged_titles_skips_blank_lines_and_comments(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "flagged_articles.log"
            log_path.write_text("\n# comment\nAlpha Town\n\nBeta_Town\n", encoding="utf-8")

            loaded = _load_flagged_titles(log_path)

        self.assertEqual(loaded, ["Alpha_Town", "Beta_Town"])


class IterArticlesTests(unittest.TestCase):
    def test_start_at_accepts_space_form_for_underscored_titles(self):
        titles = {"Alpha_Town", "Boulder_City", "Cedar_Point"}

        result = list(_iter_articles(titles, start_at="Boulder City", limit=None))

        self.assertEqual(result, ["Boulder_City", "Cedar_Point"])


class SummaryRateTests(unittest.TestCase):
    def test_format_edits_per_minute_uses_elapsed_seconds(self):
        self.assertEqual(_format_edits_per_minute(30, 120.0), "15.0")

    def test_format_edits_per_minute_handles_zero_elapsed(self):
        self.assertEqual(_format_edits_per_minute(5, 0.0), "0.0")


if __name__ == "__main__":
    unittest.main()
