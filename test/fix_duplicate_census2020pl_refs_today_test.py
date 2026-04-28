import importlib.util
import json
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "fix_duplicate_census2020pl_refs_today.py"
)
SPEC = importlib.util.spec_from_file_location(
    "fix_duplicate_census2020pl_refs_today",
    MODULE_PATH,
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class LoadSuccessfulArticlesForDateTests(unittest.TestCase):
    def test_filters_successes_by_exact_date_and_dedupes_titles(self):
        log_path = Path(self.id().replace(".", "_"))
        try:
            entries = [
                {
                    "timestamp": "2026-04-27T03:00:00Z",
                    "article": "Alpha_Town",
                    "result": {"edit": {"result": "Success", "newtimestamp": "2026-04-27T03:00:00Z"}},
                },
                {
                    "timestamp": "2026-04-27T04:00:00Z",
                    "article": "Alpha_Town",
                    "result": {"edit": {"result": "Success", "newtimestamp": "2026-04-27T04:00:00Z"}},
                },
                {
                    "timestamp": "2026-04-27T05:00:00Z",
                    "article": "Beta_Town",
                    "result": {"edit": {"result": "Failure", "newtimestamp": "2026-04-27T05:00:00Z"}},
                },
                {
                    "timestamp": "2026-04-28T01:00:00Z",
                    "article": "Gamma_Town",
                    "result": {"edit": {"result": "Success", "newtimestamp": "2026-04-28T01:00:00Z"}},
                },
            ]
            log_path.write_text(
                "".join(json.dumps(entry) + "\n" for entry in entries),
                encoding="utf-8",
            )

            titles = MODULE.load_successful_articles_for_date(
                "2026-04-27",
                log_path=log_path,
            )

            self.assertEqual(titles, ["Alpha_Town"])
        finally:
            if log_path.exists():
                log_path.unlink()


class FixDuplicatePLRefsTests(unittest.TestCase):
    def test_ignores_short_plus_single_full_ref(self):
        section = """==Demographics==
===2020 census===
Lead text.<ref name="Census2020PL"/>

{| class="wikitable"
|+ Racial composition as of the 2020 census<ref name="Census2020PL">{{cite web|title=PL|url=https://example.test/?get=NAME&for=place%3A1&in=state%3A2}}</ref>
|}
"""

        fixed, info = MODULE._fix_duplicate_pl_refs_in_section(section)

        self.assertIsNone(info)
        self.assertEqual(fixed, section)

    def test_leaves_section_unchanged_when_first_ref_is_only_full_definition(self):
        section = """==Demographics==
===2020 census===
Lead text.<ref name="Census2020PL">{{cite web|title=PL|url=https://example.test/?get=NAME}}</ref>

More text.<ref name="Census2020PL"/>
"""

        fixed, info = MODULE._fix_duplicate_pl_refs_in_section(section)

        self.assertIsNone(info)
        self.assertEqual(fixed, section)

    def test_collapses_duplicate_full_defs_in_demographics_only(self):
        article = """Lead
==Demographics==
===2020 census===
Lead text.<ref name="Census2020PL">{{cite web|title=PL|url=https://example.test/?get=NAME}}</ref>

{| class="wikitable"
|+ Racial composition as of the 2020 census<ref name="Census2020PL">{{cite web|title=PL|url=https://example.test/?get=NAME%2CP1_001N}}</ref>
|}
==References==
Outside text <ref name="Census2020PL">{{cite web|title=Outside}}</ref>
"""

        fixed, info = MODULE.fix_duplicate_pl_refs_in_article(article)

        self.assertIsNotNone(info)
        self.assertEqual(info["full_refs_before"], 2)
        self.assertEqual(fixed.count('<ref name="Census2020PL">{{cite web|title=Outside}}</ref>'), 1)
        self.assertIn('|+ Racial composition as of the 2020 census<ref name="Census2020PL"/>', fixed)
        self.assertEqual(
            fixed.count('<ref name="Census2020PL">{{cite web|title=PL|url=https://example.test/?get=NAME}}</ref>'),
            1,
        )


if __name__ == "__main__":
    unittest.main()
