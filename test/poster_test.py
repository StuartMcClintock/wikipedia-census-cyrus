from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from poster import (
    _build_edit_summary,
    apply_demographics_section_override,
    demographics_section_to_wikitext,
    find_demographics_section,
    main,
    WikipediaClient,
    WIKIPEDIA_ENDPOINT,
    ensure_us_location_title,
    parse_arguments,
)
import poster
from constants import DEFAULT_CODEX_MODEL
from llm_backends.claude_code.claude_code import (
    CLAUDE_CODE_WAIT_FOR_LIMIT_RESET_ENV,
)
from llm_backends.openai_codex.openai_codex import RUN_ARTIFACT_DIR_ENV
from llm_backends.openai_codex.openai_codex import CODEX_OUTPUT_SLOT_ENV
from parser.parser import ParsedWikitext


class DemographicsSectionHelperTests(unittest.TestCase):
    def setUp(self):
        fixture_path = Path(__file__).with_name("Coal_County_test_data.txt")
        self.wikitext = fixture_path.read_text(encoding="utf-8")
        self.parsed = ParsedWikitext(wikitext=self.wikitext)

    def test_find_demographics_section_returns_entry(self):
        result = find_demographics_section(self.parsed)
        self.assertIsNotNone(result)
        _, entry = result
        self.assertEqual(entry[0], "Demographics")

    def test_find_demographics_section_returns_none_when_missing(self):
        parsed = ParsedWikitext(wikitext="==History==\nHistory text.\n")
        self.assertIsNone(find_demographics_section(parsed))

    def test_demographics_section_to_wikitext_includes_heading(self):
        index_entry = find_demographics_section(self.parsed)
        self.assertIsNotNone(index_entry)
        _, entry = index_entry
        section_text = demographics_section_to_wikitext(entry)
        self.assertIn("==Demographics==", section_text)

    def test_apply_demographics_section_override_replaces_content(self):
        index_entry = find_demographics_section(self.parsed)
        self.assertIsNotNone(index_entry)
        index, _ = index_entry
        new_section_text = "==Demographics==\nUpdated census content.\n"
        updated_parsed = apply_demographics_section_override(
            self.parsed,
            index,
            new_section_text,
        )
        updated_text = updated_parsed.to_wikitext()
        self.assertIn("Updated census content.", updated_text)
        self.assertNotIn("Updated census content.", self.wikitext)


class WikipediaClientTests(unittest.TestCase):
    def test_skip_location_parsing_requires_manual_inputs(self):
        with patch('sys.argv', [
            'poster.py',
            '--location', 'Sample, Oklahoma',
            '--skip-location-parsing',
        ]):
            with self.assertRaises(SystemExit):
                parse_arguments()

    def test_skip_location_parsing_accepts_manual_inputs(self):
        with patch('sys.argv', [
            'poster.py',
            '--skip-location-parsing',
            '--article', 'Sample County, Oklahoma',
            '--state-fips', '40',
            '--county-fips', '029',
        ]):
            args = parse_arguments()
        self.assertTrue(args.skip_location_parsing)
        self.assertEqual(args.article, 'Sample County, Oklahoma')
        self.assertEqual(args.state_fips, '40')
        self.assertEqual(args.county_fips, '029')

    def test_parse_arguments_accepts_custom_edit_summary(self):
        with patch('sys.argv', [
            'poster.py',
            '--location', 'Sample County, Oklahoma',
            '--edit-summary', 'Custom 2020 census update',
        ]):
            args = parse_arguments()
        self.assertEqual(args.edit_summary, 'Custom 2020 census update')

    def test_parse_arguments_accepts_wait_for_claude_limit_reset(self):
        with patch('sys.argv', [
            'poster.py',
            '--location', 'Sample County, Oklahoma',
            '--wait-for-claude-limit-reset',
        ]):
            args = parse_arguments()
        self.assertTrue(args.wait_for_claude_limit_reset)

    def test_parse_arguments_accepts_run_artifact_dir(self):
        with patch('sys.argv', [
            'poster.py',
            '--location', 'Sample County, Oklahoma',
            '--run-artifact-dir', '/tmp/poster-run-a',
        ]):
            args = parse_arguments()
        self.assertEqual(args.run_artifact_dir, '/tmp/poster-run-a')

    def test_parse_arguments_accepts_codex_home_dir(self):
        with patch('sys.argv', [
            'poster.py',
            '--location', 'Sample County, Oklahoma',
            '--codex-home-dir', '/tmp/codex-home-a',
        ]):
            args = parse_arguments()
        self.assertEqual(args.codex_home_dir, '/tmp/codex-home-a')

    def test_parse_arguments_accepts_codex_output_slot(self):
        with patch('sys.argv', [
            'poster.py',
            '--location', 'Sample County, Oklahoma',
            '--codex-output-slot', '2',
        ]):
            args = parse_arguments()
        self.assertEqual(args.codex_output_slot, 2)

    def test_parse_arguments_accepts_min_muni_population_for_municipality_run(self):
        with patch('sys.argv', [
            'poster.py',
            '--municipality', 'Oktaha, Oklahoma',
            '--min-muni-population', '1000',
        ]):
            args = parse_arguments()
        self.assertEqual(args.min_muni_population, 1000)

    def test_parse_arguments_accepts_max_muni_population_for_municipality_run(self):
        with patch('sys.argv', [
            'poster.py',
            '--municipality', 'Oktaha, Oklahoma',
            '--max-muni-population', '5000',
        ]):
            args = parse_arguments()
        self.assertEqual(args.max_muni_population, 5000)

    def test_parse_arguments_rejects_min_muni_population_for_county_run(self):
        with patch('sys.argv', [
            'poster.py',
            '--location', 'Coal County, Oklahoma',
            '--min-muni-population', '1000',
        ]):
            with self.assertRaises(SystemExit):
                parse_arguments()

    def test_parse_arguments_rejects_max_muni_population_for_county_run(self):
        with patch('sys.argv', [
            'poster.py',
            '--location', 'Coal County, Oklahoma',
            '--max-muni-population', '5000',
        ]):
            with self.assertRaises(SystemExit):
                parse_arguments()

    def test_parse_arguments_rejects_min_above_max_for_municipality_run(self):
        with patch('sys.argv', [
            'poster.py',
            '--municipality', 'Oktaha, Oklahoma',
            '--min-muni-population', '5000',
            '--max-muni-population', '1000',
        ]):
            with self.assertRaises(SystemExit):
                parse_arguments()

    def test_parse_arguments_start_state_sets_filtered_state_postals(self):
        with patch('sys.argv', [
            'poster.py',
            '--state-postal', 'ALL',
            '--start-state', 'CO',
        ]):
            args = parse_arguments()
        self.assertEqual(args.state_postals[0], 'CO')
        self.assertNotIn('CA', args.state_postals)

    def test_main_uses_filtered_state_postals(self):
        args = Mock(
            model=None,
            skip_logged_successes=False,
            municipality=None,
            place_fips=None,
            state_postal='ALL',
            state_postals=['CO', 'CT'],
            municipality_type=None,
            start_county_fips=None,
            start_muni_fips=None,
        )
        client = Mock()

        with patch.object(poster, 'parse_arguments', return_value=args):
            with patch.object(poster, 'WikipediaClient', return_value=client):
                with patch.object(poster, 'process_state_batch') as process_state_batch:
                    main()

        client.login.assert_called_once()
        self.assertEqual(
            [call.args[0] for call in process_state_batch.call_args_list],
            ['CO', 'CT'],
        )

    def test_main_sets_claude_limit_reset_env_when_requested(self):
        args = Mock(
            model='claude-sonnet-4-6',
            run_artifact_dir=None,
            wait_for_claude_limit_reset=True,
            skip_logged_successes=False,
            municipality=None,
            place_fips=None,
            state_postal='OK',
            state_postals=['OK'],
            municipality_type=None,
            start_county_fips=None,
            start_muni_fips=None,
        )
        client = Mock()

        with patch.dict(os.environ, {}, clear=False):
            with patch.object(poster, 'parse_arguments', return_value=args):
                with patch.object(poster, 'WikipediaClient', return_value=client):
                    with patch.object(poster, 'process_state_batch'):
                        main()

            self.assertEqual(
                os.environ.get(CLAUDE_CODE_WAIT_FOR_LIMIT_RESET_ENV),
                '1',
            )

    def test_main_sets_run_artifact_dir_env_when_requested(self):
        args = Mock(
            model=None,
            run_artifact_dir='/tmp/poster-run-b',
            codex_home_dir=None,
            codex_output_slot=None,
            wait_for_claude_limit_reset=False,
            skip_logged_successes=False,
            municipality=None,
            place_fips=None,
            state_postal='OK',
            state_postals=['OK'],
            municipality_type=None,
            start_county_fips=None,
            start_muni_fips=None,
        )
        client = Mock()

        with patch.dict(os.environ, {}, clear=False):
            with patch.object(poster, 'parse_arguments', return_value=args):
                with patch.object(poster, 'WikipediaClient', return_value=client):
                    with patch.object(poster, 'process_state_batch'):
                        main()

            self.assertEqual(
                os.environ.get(RUN_ARTIFACT_DIR_ENV),
                '/tmp/poster-run-b',
            )

    def test_main_sets_codex_home_env_when_requested(self):
        args = Mock(
            model=None,
            run_artifact_dir=None,
            codex_home_dir='/tmp/codex-home-b',
            codex_output_slot=None,
            wait_for_claude_limit_reset=False,
            skip_logged_successes=False,
            municipality=None,
            place_fips=None,
            state_postal='OK',
            state_postals=['OK'],
            municipality_type=None,
            start_county_fips=None,
            start_muni_fips=None,
        )
        client = Mock()

        with patch.dict(os.environ, {}, clear=False):
            with patch.object(poster, 'parse_arguments', return_value=args):
                with patch.object(poster, 'WikipediaClient', return_value=client):
                    with patch.object(poster, 'process_state_batch'):
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
            municipality=None,
            place_fips=None,
            state_postal='OK',
            state_postals=['OK'],
            municipality_type=None,
            start_county_fips=None,
            start_muni_fips=None,
        )
        client = Mock()

        with patch.dict(os.environ, {}, clear=False):
            with patch.object(poster, 'parse_arguments', return_value=args):
                with patch.object(poster, 'WikipediaClient', return_value=client):
                    with patch.object(poster, 'process_state_batch'):
                        main()

            self.assertEqual(
                os.environ.get(CODEX_OUTPUT_SLOT_ENV),
                '2',
            )

    def test_parse_arguments_accepts_supported_new_model(self):
        with patch('sys.argv', [
            'poster.py',
            '--location', 'Coal County, Oklahoma',
            '--model', 'gpt-5.4',
        ]):
            args = parse_arguments()
        self.assertEqual(args.model, 'gpt-5.4')

    def test_parse_arguments_accepts_claude_cli_haiku_alias(self):
        with patch('sys.argv', [
            'poster.py',
            '--location', 'Coal County, Oklahoma',
            '--model', 'haiku',
        ]):
            args = parse_arguments()
        self.assertEqual(args.model, 'haiku')

    def test_main_uses_mini_prompt_for_mini_models(self):
        args = Mock(
            model='gpt-5.4-mini',
            skip_logged_successes=False,
            municipality=None,
            place_fips=None,
            state_postal='OK',
            state_postals=['OK'],
            municipality_type=None,
            start_county_fips=None,
            start_muni_fips=None,
        )
        client = Mock()

        with patch.object(poster, 'parse_arguments', return_value=args):
            with patch.object(poster, 'WikipediaClient', return_value=client):
                with patch.object(poster, 'process_state_batch') as process_state_batch:
                    main()

        self.assertEqual(process_state_batch.call_args.args[3], True)

    def test_process_municipality_batch_accepts_all_types(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            city_dir = root / "CA" / "city"
            town_dir = root / "CA" / "town"
            city_dir.mkdir(parents=True, exist_ok=True)
            town_dir.mkdir(parents=True, exist_ok=True)
            (city_dir / "places.json").write_text(
                json.dumps(
                    {
                        "Alpha, California": {
                            "state": "06",
                            "place": "00100",
                            "population": "100",
                        }
                    }
                ),
                encoding="utf-8",
            )
            (town_dir / "places.json").write_text(
                json.dumps(
                    {
                        "Beta, California": {
                            "state": "06",
                            "place": "00200",
                            "population": "200",
                        }
                    }
                ),
                encoding="utf-8",
            )

            args = Mock(min_muni_population=None, max_muni_population=None)
            calls = []

            def fake_process(
                article_title,
                state_fips,
                place_fips,
                args,
                client,
                use_mini_prompt,
                skip_successful_articles=None,
                location_kind="county",
                expected_muni_type=None,
                expected_mapper_population=None,
                use_population_ballpark_check=False,
            ):
                calls.append(
                    (
                        article_title,
                        state_fips,
                        place_fips,
                        expected_muni_type,
                        expected_mapper_population,
                        use_population_ballpark_check,
                    )
                )

            with patch.object(poster, "MUNICIPALITY_FIPS_DIR", root):
                with patch.object(
                    poster,
                    "process_single_article_with_retries",
                    side_effect=fake_process,
                ):
                    poster.process_municipality_batch(
                        "CA",
                        "ALL",
                        client=None,
                        args=args,
                        use_mini_prompt=False,
                    )

            self.assertEqual(
                calls,
                [
                    ("Alpha,_California", "06", "00100", "city", 100, True),
                    ("Beta,_California", "06", "00200", "town", 200, True),
                ],
            )

    def test_build_edit_summary_uses_custom_when_not_manual(self):
        summary = _build_edit_summary('Custom 2020 census update', manual_review=False)
        self.assertEqual(summary, 'Custom 2020 census update')

    def test_build_edit_summary_uses_default_when_no_custom(self):
        summary = _build_edit_summary(None, manual_review=False)
        self.assertEqual(summary, 'Add 2020 census data')

    def test_build_edit_summary_manual_review_overrides_custom(self):
        summary = _build_edit_summary('Custom 2020 census update', manual_review=True)
        self.assertEqual(summary, 'Add 2020 census data (manual review)')

    def test_ensure_us_location_title_accepts_us_titles(self):
        ensure_us_location_title("Coalgate,_Oklahoma")
        ensure_us_location_title("Springfield,_Illinois")
        ensure_us_location_title("Washington,_District_of_Columbia")

    def test_ensure_us_location_title_rejects_non_us_titles(self):
        with self.assertRaises(ValueError):
            ensure_us_location_title("London")
        with self.assertRaises(ValueError):
            ensure_us_location_title("Sydney,_Australia")
        with self.assertRaises(ValueError):
            ensure_us_location_title("SomePageWithoutSuffix")

    @patch('poster.requests.Session')
    def test_get_login_token_requests_token(self, mock_session_cls):
        mock_session = mock_session_cls.return_value
        mock_session.headers = {}
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            'query': {'tokens': {'logintoken': 'TOKEN123'}}
        }
        mock_session.get.return_value = mock_response

        client = WikipediaClient('TestAgent/1.0')
        token = client.get_login_token()

        self.assertEqual(token, 'TOKEN123')
        mock_session.get.assert_called_once_with(
            WIKIPEDIA_ENDPOINT,
            params={
                'action': 'query',
                'meta': 'tokens',
                'type': 'login',
                'format': 'json'
            },
        )

    @patch('poster.requests.Session')
    def test_login_successful(self, mock_session_cls):
        mock_session = mock_session_cls.return_value
        mock_session.headers = {}
        client = WikipediaClient('TestAgent/1.0')

        with patch.object(client, 'get_login_token', return_value='TOKEN123'):
            with patch('poster.print') as mock_print:
                mock_response = Mock()
                mock_response.raise_for_status = Mock()
                mock_response.json.return_value = {'login': {'result': 'Success'}}
                mock_session.post.return_value = mock_response

                result = client.login('user', 'pass')

            expected_payload = {
                'action': 'login',
                'lgname': 'user',
                'lgpassword': 'pass',
                'lgtoken': 'TOKEN123',
                'format': 'json'
            }
            mock_session.post.assert_called_once_with(
                WIKIPEDIA_ENDPOINT,
                data=expected_payload,
            )
            self.assertEqual(result, {'login': {'result': 'Success'}})
            mock_print.assert_called_once_with("Successfully logged in as user")

    @patch('poster.requests.Session')
    def test_login_failure_raises(self, mock_session_cls):
        mock_session = mock_session_cls.return_value
        mock_session.headers = {}
        client = WikipediaClient('TestAgent/1.0')

        with patch.object(client, 'get_login_token', return_value='TOKEN123'):
            mock_response = Mock()
            mock_response.raise_for_status = Mock()
            mock_response.json.return_value = {'login': {'result': 'Failed'}}
            mock_session.post.return_value = mock_response

            with self.assertRaises(Exception):
                client.login('user', 'pass')

    @patch('poster.requests.Session')
    def test_fetch_article_wikitext_returns_content(self, mock_session_cls):
        mock_session = mock_session_cls.return_value
        mock_session.headers = {}
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            'query': {
                'pages': [
                    {
                        'revisions': [
                            {
                                'slots': {
                                    'main': {
                                        'content': 'Sample wikitext'
                                    }
                                }
                            }
                        ]
                    }
                ]
            }
        }
        mock_session.get.return_value = mock_response

        client = WikipediaClient('TestAgent/1.0')
        wikitext = client.fetch_article_wikitext('Sample')

        self.assertEqual(wikitext, 'Sample wikitext')
        mock_session.get.assert_called_once_with(
            WIKIPEDIA_ENDPOINT,
            params={
                'action': 'query',
                'prop': 'revisions',
                'titles': 'Sample',
                'rvprop': 'content',
                'rvslots': 'main',
                'formatversion': '2',
                'format': 'json'
            },
        )

    @patch('poster.requests.Session')
    def test_compare_revision_sizes_returns_delta(self, mock_session_cls):
        mock_session = mock_session_cls.return_value
        mock_session.headers = {}
        client = WikipediaClient('TestAgent/1.0')

        compare_response = Mock()
        compare_response.raise_for_status = Mock()
        compare_response.json.return_value = {
            'compare': {'fromsize': 1000, 'tosize': 1300}
        }

        with patch.object(client, '_get', return_value=compare_response) as mock_get:
            delta = client.compare_revision_sizes(111, 222)

        self.assertEqual(delta, 300)
        mock_get.assert_called_once_with(
            {
                'action': 'compare',
                'fromrev': 111,
                'torev': 222,
                'prop': 'size',
                'format': 'json',
            }
        )

    @patch('poster.requests.Session')
    def test_compare_revision_sizes_missing_info_raises(self, mock_session_cls):
        mock_session = mock_session_cls.return_value
        mock_session.headers = {}
        client = WikipediaClient('TestAgent/1.0')

        compare_response = Mock()
        compare_response.raise_for_status = Mock()
        compare_response.json.return_value = {'compare': {}}

        with patch.object(client, '_get', return_value=compare_response):
            with self.assertRaises(ValueError):
                client.compare_revision_sizes(111, 222)

    @patch('poster.requests.Session')
    def test_edit_article_with_size_check_success(self, mock_session_cls):
        mock_session = mock_session_cls.return_value
        mock_session.headers = {}
        client = WikipediaClient('TestAgent/1.0')
        parsed = ParsedWikitext(wikitext="Original lead text.\n")
        parsed.overwrite_section(["__lead__"], "Updated lead text.\n")
        expected_delta = len(parsed.to_wikitext()) - parsed.original_length

        with patch.object(
            client,
            'edit_article_wikitext',
            return_value={'edit': {'oldrevid': 1, 'newrevid': 2}},
        ) as mock_edit, patch.object(
            client, 'compare_revision_sizes', return_value=expected_delta
        ) as mock_compare:
            response = client.edit_article_with_size_check("Sample,_Oklahoma", parsed, "summary")

        mock_edit.assert_called_once()
        mock_compare.assert_called_once_with(1, 2)
        self.assertEqual(response, {'edit': {'oldrevid': 1, 'newrevid': 2}})

    @patch('poster.requests.Session')
    def test_edit_article_with_size_check_raises_on_mismatch(self, mock_session_cls):
        mock_session = mock_session_cls.return_value
        mock_session.headers = {}
        client = WikipediaClient('TestAgent/1.0')
        parsed = ParsedWikitext(wikitext="Original lead text.\n")
        parsed.overwrite_section(["__lead__"], "Updated lead text.\n")

        with patch.object(
            client,
            'edit_article_wikitext',
            return_value={'edit': {'oldrevid': 1, 'newrevid': 2}},
        ), patch.object(
            client, 'compare_revision_sizes', return_value=9999
        ):
            with self.assertRaises(ValueError):
                client.edit_article_with_size_check("Sample,_Oklahoma", parsed, "summary", tolerance=10)

    @patch('poster.requests.Session')
    def test_edit_article_with_size_check_skips_compare_when_ids_missing(self, mock_session_cls):
        mock_session = mock_session_cls.return_value
        mock_session.headers = {}
        client = WikipediaClient('TestAgent/1.0')
        parsed = ParsedWikitext(wikitext="Original lead text.\n")
        parsed.overwrite_section(["__lead__"], "Updated lead text.\n")

        with patch.object(
            client,
            'edit_article_wikitext',
            return_value={'edit': {'result': 'Success'}},
        ) as mock_edit, patch.object(
            client, 'compare_revision_sizes'
        ) as mock_compare:
            response = client.edit_article_with_size_check("Sample,_Oklahoma", parsed, "summary")

        mock_edit.assert_called_once()
        mock_compare.assert_not_called()
        self.assertEqual(response, {'edit': {'result': 'Success'}})


if __name__ == '__main__':
    unittest.main()
