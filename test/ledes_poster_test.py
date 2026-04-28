import unittest
import json
import os
import tempfile
import types
from pathlib import Path
from unittest.mock import Mock, patch

import ledes_poster
from ledes_poster import (
    _build_population_sentence,
    _fetch_place_population,
    _replace_lede_in_article,
    _extract_lede_wikitext,
    _append_diff_link,
    LLMQuotaExceededError,
    main,
    parse_arguments,
    process_municipality_batch,
    process_single_article_with_retries,
)
from llm_backends.claude_code.claude_code import (
    CLAUDE_CODE_WAIT_FOR_LIMIT_RESET_ENV,
)
from llm_backends.openai_codex.openai_codex import (
    CODEX_OUTPUT_SLOT_ENV,
    RUN_ARTIFACT_DIR_ENV,
)
from parser.parser import ParsedWikitext


class LedesPosterTests(unittest.TestCase):
    def test_build_population_sentence_includes_ref(self):
        sentence = _build_population_sentence(
            "Sampleville, Oklahoma",
            12345,
            "https://api.census.gov/data/2020/dec/pl?get=NAME,P1_001N&for=place:12345&in=state:12",
        )
        self.assertIn("As of the [[2020 United States census|2020 census]]", sentence)
        self.assertIn("Sampleville had a population of 12,345.", sentence)
        self.assertIn("https://api.census.gov/data/2020/dec/pl?get=NAME,P1_001N", sentence)
        self.assertIn('<ref name="Census2020PLLede">', sentence)

    def test_fetch_place_population_parses_response(self):
        payload = [
            ["NAME", "P1_001N", "state", "place"],
            ["Sampleville, Test", "456", "12", "12345"],
        ]

        class FakeResponse:
            def __init__(self, data, url):
                self._data = data
                self.url = url

            def raise_for_status(self):
                return None

            def json(self):
                return self._data

        fake_url = "https://api.census.gov/data/2020/dec/pl?get=NAME,P1_001N&for=place:12345&in=state:12"
        with patch("ledes_poster.requests.get", return_value=FakeResponse(payload, fake_url)):
            name, population, url = _fetch_place_population("12", "12345")

        self.assertEqual(name, "Sampleville, Test")
        self.assertEqual(population, 456)
        self.assertEqual(url, fake_url)

    def test_replace_lede_in_article(self):
        article = "Original lead.\n\n==History==\nSome history.\n"
        updated_lede = "Updated lead.\n\n"
        updated_article = _replace_lede_in_article(article, updated_lede)

        parsed = ParsedWikitext(wikitext=updated_article)
        self.assertEqual(_extract_lede_wikitext(parsed), updated_lede)
        self.assertIn("==History==", updated_article)
        self.assertIn("Some history.", updated_article)
        self.assertTrue(updated_article.startswith(updated_lede))

    def test_append_diff_link_writes_url(self):
        with self.subTest("success write"):
            with patch("ledes_poster.DIFF_LOG_PATH") as diff_path:
                diff_path.parent.mkdir = lambda parents=True, exist_ok=True: None
                buffer = []

                class DummyFile:
                    def __enter__(self):
                        return self

                    def __exit__(self, exc_type, exc, tb):
                        return False

                    def write(self, text):
                        buffer.append(text)

                diff_path.open = lambda *args, **kwargs: DummyFile()
                response = {
                    "edit": {
                        "result": "Success",
                        "oldrevid": 1,
                        "newrevid": 2,
                        "title": "Sample Town, Test",
                    }
                }
                _append_diff_link("Sample_Town,_Test", response)
                self.assertEqual(
                    buffer[0].strip(),
                    "https://en.wikipedia.org/w/index.php?title=Sample_Town,_Test&diff=2&oldid=1",
                )

        with self.subTest("non-success ignored"):
            with patch("ledes_poster.DIFF_LOG_PATH") as diff_path:
                diff_path.parent.mkdir = lambda parents=True, exist_ok=True: None
                buffer = []

                class DummyFile:
                    def __enter__(self):
                        return self

                    def __exit__(self, exc_type, exc, tb):
                        return False

                    def write(self, text):
                        buffer.append(text)

                diff_path.open = lambda *args, **kwargs: DummyFile()
                response = {"edit": {"result": "Failure", "oldrevid": 1, "newrevid": 2}}
                _append_diff_link("Sample_Town,_Test", response)
                self.assertEqual(buffer, [])

    def test_random_delay_runs_only_after_successful_post(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            places_dir = root / "OK" / "city"
            places_dir.mkdir(parents=True, exist_ok=True)
            (places_dir / "places.json").write_text(
                json.dumps(
                    {
                        "Sampleville, Oklahoma": {"state": "40", "place": "12345"},
                    }
                ),
                encoding="utf-8",
            )

            args = types.SimpleNamespace(random_delay=True)

            with patch("ledes_poster.MUNICIPALITY_FIPS_DIR", root):
                with patch("ledes_poster.process_single_article_with_retries", return_value=False):
                    with patch("ledes_poster.random.uniform", return_value=31.5):
                        with patch("ledes_poster.time.sleep") as sleep_mock:
                            process_municipality_batch("OK", "city", client=None, args=args)
                            sleep_mock.assert_not_called()

                with patch("ledes_poster.process_single_article_with_retries", return_value=True):
                    with patch("ledes_poster.random.uniform", return_value=31.5):
                        with patch("ledes_poster.time.sleep") as sleep_mock:
                            process_municipality_batch("OK", "city", client=None, args=args)
                            sleep_mock.assert_called_once_with(31.5)

    def test_process_single_article_with_retries_raises_on_quota_error(self):
        with patch(
            "ledes_poster.process_single_article",
            side_effect=RuntimeError("insufficient_quota: account out of credits"),
        ):
            with self.assertRaises(LLMQuotaExceededError):
                process_single_article_with_retries(
                    "Sampleville,_Oklahoma",
                    "40",
                    "12345",
                    args=types.SimpleNamespace(),
                    client=None,
                )

    def test_process_single_article_with_retries_raises_on_openai_rate_limit_quota_error(self):
        import httpx
        import openai

        req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        resp = httpx.Response(429, request=req)
        err = openai.RateLimitError(
            "You exceeded your current quota.",
            response=resp,
            body={"code": "insufficient_quota"},
        )

        with patch("ledes_poster.process_single_article", side_effect=err):
            with self.assertRaises(LLMQuotaExceededError):
                process_single_article_with_retries(
                    "Sampleville,_Oklahoma",
                    "40",
                    "12345",
                    args=types.SimpleNamespace(),
                    client=None,
                )

    def test_process_municipality_batch_raises_on_quota_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            places_dir = root / "OK" / "city"
            places_dir.mkdir(parents=True, exist_ok=True)
            (places_dir / "places.json").write_text(
                json.dumps(
                    {
                        "Sampleville, Oklahoma": {"state": "40", "place": "12345"},
                    }
                ),
                encoding="utf-8",
            )

            args = types.SimpleNamespace(random_delay=False)
            with patch("ledes_poster.MUNICIPALITY_FIPS_DIR", root):
                with patch(
                    "ledes_poster.process_single_article_with_retries",
                    side_effect=LLMQuotaExceededError("LLM quota exhausted"),
                ):
                    with self.assertRaises(LLMQuotaExceededError):
                        process_municipality_batch("OK", "city", client=None, args=args)

    def test_parse_arguments_start_state_sets_filtered_state_postals(self):
        with patch('sys.argv', [
            'ledes_poster.py',
            '--state-postal', 'ALL',
            '--municipality-type', 'city',
            '--start-state', 'CO',
        ]):
            args = parse_arguments()
        self.assertEqual(args.state_postals[0], 'CO')
        self.assertNotIn('CA', args.state_postals)

    def test_parse_arguments_accepts_codex_output_slot(self):
        with patch('sys.argv', [
            'ledes_poster.py',
            '--state-postal', 'OR',
            '--municipality-type', 'city',
            '--codex-output-slot', '2',
        ]):
            args = parse_arguments()
        self.assertEqual(args.codex_output_slot, 2)

    def test_main_uses_filtered_state_postals(self):
        args = Mock(
            model=None,
            skip_logged_successes=False,
            state_postal='ALL',
            state_postals=['CO', 'CT'],
            municipality_type='city',
            start_muni_fips=None,
            municipality=None,
            place_fips=None,
        )
        client = Mock()

        with patch.object(ledes_poster, 'parse_arguments', return_value=args):
            with patch.object(ledes_poster, 'WikipediaClient', return_value=client):
                with patch.object(ledes_poster, 'process_municipality_batch') as process_batch:
                    main()

        client.login.assert_called_once()
        self.assertEqual(
            [call.args[0] for call in process_batch.call_args_list],
            ['CO', 'CT'],
        )

    def test_main_sets_claude_limit_reset_env_when_requested(self):
        args = Mock(
            model='claude-sonnet-4-6',
            run_artifact_dir=None,
            wait_for_claude_limit_reset=True,
            skip_logged_successes=False,
            state_postal='OR',
            state_postals=['OR'],
            municipality_type='city',
            start_muni_fips=None,
            municipality=None,
            place_fips=None,
        )
        client = Mock()

        with patch.dict(os.environ, {}, clear=False):
            with patch.object(ledes_poster, 'parse_arguments', return_value=args):
                with patch.object(ledes_poster, 'WikipediaClient', return_value=client):
                    with patch.object(ledes_poster, 'process_municipality_batch'):
                        main()

            self.assertEqual(
                os.environ.get(CLAUDE_CODE_WAIT_FOR_LIMIT_RESET_ENV),
                '1',
            )

    def test_main_sets_run_artifact_dir_env_when_requested(self):
        args = Mock(
            model=None,
            run_artifact_dir='/tmp/ledes-run-b',
            codex_home_dir=None,
            codex_output_slot=None,
            wait_for_claude_limit_reset=False,
            skip_logged_successes=False,
            state_postal='OR',
            state_postals=['OR'],
            municipality_type='city',
            start_muni_fips=None,
            municipality=None,
            place_fips=None,
        )
        client = Mock()

        with patch.dict(os.environ, {}, clear=False):
            with patch.object(ledes_poster, 'parse_arguments', return_value=args):
                with patch.object(ledes_poster, 'WikipediaClient', return_value=client):
                    with patch.object(ledes_poster, 'process_municipality_batch'):
                        main()

            self.assertEqual(
                os.environ.get(RUN_ARTIFACT_DIR_ENV),
                '/tmp/ledes-run-b',
            )

    def test_main_sets_codex_home_env_when_requested(self):
        args = Mock(
            model=None,
            run_artifact_dir=None,
            codex_home_dir='/tmp/codex-home-b',
            codex_output_slot=None,
            wait_for_claude_limit_reset=False,
            skip_logged_successes=False,
            state_postal='OR',
            state_postals=['OR'],
            municipality_type='city',
            start_muni_fips=None,
            municipality=None,
            place_fips=None,
        )
        client = Mock()

        with patch.dict(os.environ, {}, clear=False):
            with patch.object(ledes_poster, 'parse_arguments', return_value=args):
                with patch.object(ledes_poster, 'WikipediaClient', return_value=client):
                    with patch.object(ledes_poster, 'process_municipality_batch'):
                        main()

            self.assertEqual(
                os.environ.get("CODEX_HOME"),
                '/tmp/codex-home-b',
            )

    def test_main_sets_codex_output_slot_env_when_requested(self):
        args = Mock(
            model=None,
            run_artifact_dir=None,
            codex_home_dir=None,
            codex_output_slot=2,
            wait_for_claude_limit_reset=False,
            skip_logged_successes=False,
            state_postal='OR',
            state_postals=['OR'],
            municipality_type='city',
            start_muni_fips=None,
            municipality=None,
            place_fips=None,
        )
        client = Mock()

        with patch.dict(os.environ, {}, clear=False):
            with patch.object(ledes_poster, 'parse_arguments', return_value=args):
                with patch.object(ledes_poster, 'WikipediaClient', return_value=client):
                    with patch.object(ledes_poster, 'process_municipality_batch'):
                        main()

            self.assertEqual(
                os.environ.get(CODEX_OUTPUT_SLOT_ENV),
                '2',
            )


if __name__ == "__main__":
    unittest.main()
