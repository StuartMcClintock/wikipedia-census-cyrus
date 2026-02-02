import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

import ledes_poster


class LedesPosterCliTests(unittest.TestCase):
    def test_start_muni_fips_requires_state_postal(self):
        argv = [
            "ledes_poster.py",
            "--start-muni-fips",
            "31050",
            "--municipality-type",
            "city",
        ]
        with patch.object(sys, "argv", argv):
            with redirect_stderr(StringIO()), redirect_stdout(StringIO()):
                with self.assertRaises(SystemExit):
                    ledes_poster.parse_arguments()

    def test_start_muni_fips_requires_municipality_type(self):
        argv = [
            "ledes_poster.py",
            "--state-postal",
            "OR",
            "--start-muni-fips",
            "31050",
        ]
        with patch.object(sys, "argv", argv):
            with redirect_stderr(StringIO()), redirect_stdout(StringIO()):
                with self.assertRaises(SystemExit):
                    ledes_poster.parse_arguments()

    def test_main_passes_start_and_skip_logged(self):
        argv = [
            "ledes_poster.py",
            "--state-postal",
            "OR",
            "--municipality-type",
            "city",
            "--start-muni-fips",
            "31050",
            "--skip-logged-successes",
        ]
        captured = {}

        class DummyClient:
            def __init__(self, *args, **kwargs):
                pass

            def login(self, *args, **kwargs):
                return None

        def fake_batch(state_postal, municipality_type, client, args, start_muni_fips=None, skip_successful_articles=None):
            captured["state_postal"] = state_postal
            captured["municipality_type"] = municipality_type
            captured["start_muni_fips"] = start_muni_fips
            captured["skip_successful_articles"] = skip_successful_articles

        with patch.object(sys, "argv", argv):
            with patch("ledes_poster.WikipediaClient", DummyClient):
                with patch("ledes_poster._load_successful_articles", return_value={"A", "B"}):
                    with patch("ledes_poster.process_municipality_batch", side_effect=fake_batch):
                        ledes_poster.main()

        self.assertEqual(captured.get("start_muni_fips"), "31050")
        self.assertEqual(captured.get("skip_successful_articles"), {"A", "B"})


if __name__ == "__main__":
    unittest.main()
