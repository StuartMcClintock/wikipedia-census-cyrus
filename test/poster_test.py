from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from poster import (
    _handle_sigint,
    _reset_interrupt_state,
    _should_stop_after_current_article,
    _build_edit_summary,
    apply_demographics_section_override,
    apply_precomputed_demographics_section,
    demographics_section_to_wikitext,
    find_demographics_section,
    insert_demographics_section,
    load_precomputed_section,
    main,
    process_single_article,
    write_precomputed_section,
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
from llm_frontend import ENABLE_TASK_MODEL_ROUTING_ENV
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

    def test_insert_demographics_section_places_new_section_before_references(self):
        parsed = ParsedWikitext(
            wikitext="Lead text.\n==History==\nHistory text.\n==References==\nRef text.\n"
        )

        updated_parsed = insert_demographics_section(
            parsed,
            "===2020 census===\n\nNew census content.\n",
        )

        updated_text = updated_parsed.to_wikitext()
        self.assertIn("==Demographics==\n===2020 census===\n\nNew census content.\n", updated_text)
        self.assertLess(updated_text.find("==Demographics=="), updated_text.find("==References=="))

    def test_apply_precomputed_demographics_section_replaces_existing_section(self):
        parsed = ParsedWikitext(
            wikitext="==Demographics==\nOld content.\n==References==\nRef text.\n"
        )

        updated_parsed = apply_precomputed_demographics_section(
            parsed,
            "==Demographics==\n===2020 census===\n\nCached content.\n",
        )

        updated_text = updated_parsed.to_wikitext()
        self.assertIn("Cached content.", updated_text)
        self.assertNotIn("Old content.", updated_text)

    def test_write_and_load_precomputed_section_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            args = Mock(
                precomputed_root=tmpdir,
                edit_summary=None,
                manual_review=False,
            )
            with patch.object(poster, "log_precomputed_article"):
                metadata = write_precomputed_section(
                    article_title="Sample_County,_Oklahoma",
                    location_kind="county",
                    state_fips="40",
                    target_fips="001",
                    section_text="==Demographics==\n===2020 census===\n\nCached content.\n",
                    had_demographics_section=False,
                    args=args,
                )
                loaded_metadata, loaded_text = load_precomputed_section(
                    article_title="Sample_County,_Oklahoma",
                    location_kind="county",
                    state_fips="40",
                    target_fips="001",
                    args=args,
                )

        self.assertEqual(loaded_metadata["article"], "Sample_County,_Oklahoma")
        self.assertEqual(loaded_text, "==Demographics==\n===2020 census===\n\nCached content.\n")
        self.assertEqual(metadata["section_path"], loaded_metadata["section_path"])


class InterruptHandlingTests(unittest.TestCase):
    def tearDown(self):
        _reset_interrupt_state()

    def test_first_ctrl_c_requests_stop_after_current_article(self):
        _reset_interrupt_state()

        with patch.object(poster, "print") as mock_print:
            _handle_sigint(None, None)

        self.assertTrue(_should_stop_after_current_article())
        self.assertIn("stop after the current article finishes", mock_print.call_args.args[0])

    def test_second_ctrl_c_uses_default_interrupt_handler(self):
        _reset_interrupt_state()

        with patch.object(poster.signal, "default_int_handler") as default_handler:
            _handle_sigint(None, None)
            _handle_sigint(None, None)

        default_handler.assert_called_once()


class WikipediaClientTests(unittest.TestCase):
    def test_process_single_article_inserts_demographics_when_missing(self):
        args = Mock(
            show_codex_output=False,
            skip_should_update_check=False,
            skip_deterministic_fixes=True,
            edit_summary=None,
            manual_review=False,
        )
        client = Mock()
        client.is_disambiguation_page.return_value = False
        client.fetch_article_wikitext.return_value = (
            "Lead text.\n==History==\nHistory text.\n==References==\nRef text.\n"
        )
        client.edit_article_wikitext.return_value = {"edit": {"result": "Success"}}

        with patch.object(
            poster,
            "generate_county_paragraphs",
            return_value="===2020 census===\n\nNew census content.\n",
        ):
            with patch.object(poster, "check_if_update_needed", return_value=True):
                with patch.object(poster, "update_wp_page") as update_wp_page:
                    with patch.object(poster, "_append_diff_link"):
                        with patch.object(poster, "pprint"):
                            process_single_article(
                                "Sample_County,_Oklahoma",
                                "40",
                                "001",
                                args,
                                client,
                                use_mini_prompt=False,
                            )

        update_wp_page.assert_not_called()
        edited_text = client.edit_article_wikitext.call_args.args[1]
        self.assertIn("==Demographics==", edited_text)
        self.assertIn("===2020 census===\n\nNew census content.\n", edited_text)
        self.assertLess(edited_text.find("==Demographics=="), edited_text.find("==References=="))

    def test_process_single_article_precompute_only_writes_cache_and_skips_edit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            args = Mock(
                show_codex_output=False,
                skip_should_update_check=False,
                skip_deterministic_fixes=False,
                edit_summary=None,
                manual_review=False,
                precompute_only=True,
                post_precomputed=False,
                precomputed_root=tmpdir,
            )
            client = Mock()
            client.is_disambiguation_page.return_value = False
            client.fetch_article_wikitext.return_value = (
                "==Demographics==\nOld content.\n==References==\nRef text.\n"
            )

            with patch.object(
                poster,
                "generate_county_paragraphs",
                return_value="===2020 census===\n\nNew census content.\n",
            ):
                with patch.object(poster, "check_if_update_needed", return_value=True):
                    with patch.object(
                        poster,
                        "update_demographics_section",
                        return_value="==Demographics==\n===2020 census===\n\nNew census content.\n",
                    ):
                        with patch.object(poster, "log_precomputed_article"):
                            process_single_article(
                                "Sample_County,_Oklahoma",
                                "40",
                                "001",
                                args,
                                client,
                                use_mini_prompt=False,
                            )

            client.edit_article_wikitext.assert_not_called()
            manifest_path = (
                Path(tmpdir)
                / "county"
                / "40"
                / "001"
                / "Sample_County__Oklahoma"
                / "manifest.json"
            )
            section_path = manifest_path.parent / "demographics_section.wikitext"
            self.assertTrue(manifest_path.exists())
            self.assertTrue(section_path.exists())
            self.assertIn("New census content.", section_path.read_text(encoding="utf-8"))

    def test_process_single_article_post_precomputed_uses_cache_and_posts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            precompute_args = Mock(
                precomputed_root=tmpdir,
                edit_summary=None,
                manual_review=False,
            )
            with patch.object(poster, "log_precomputed_article"):
                write_precomputed_section(
                    article_title="Sample_County,_Oklahoma",
                    location_kind="county",
                    state_fips="40",
                    target_fips="001",
                    section_text="==Demographics==\n===2020 census===\n\nCached content.\n",
                    had_demographics_section=False,
                    args=precompute_args,
                )

            args = Mock(
                show_codex_output=False,
                skip_should_update_check=False,
                skip_deterministic_fixes=False,
                edit_summary=None,
                manual_review=False,
                precompute_only=False,
                post_precomputed=True,
                precomputed_root=tmpdir,
            )
            client = Mock()
            client.is_disambiguation_page.return_value = False
            client.fetch_article_wikitext.return_value = (
                "Lead text.\n==History==\nHistory text.\n==References==\nRef text.\n"
            )
            client.edit_article_wikitext.return_value = {"edit": {"result": "Success"}}

            with patch.object(poster, "generate_county_paragraphs") as generate_county_paragraphs:
                with patch.object(poster, "update_demographics_section") as update_demographics_section:
                    with patch.object(poster, "update_wp_page") as update_wp_page:
                        with patch.object(poster, "_append_diff_link"):
                            with patch.object(poster, "pprint"):
                                process_single_article(
                                    "Sample_County,_Oklahoma",
                                    "40",
                                    "001",
                                    args,
                                    client,
                                    use_mini_prompt=False,
                                )

            generate_county_paragraphs.assert_not_called()
            update_demographics_section.assert_not_called()
            update_wp_page.assert_not_called()
            edited_text = client.edit_article_wikitext.call_args.args[1]
            self.assertIn("Cached content.", edited_text)
            self.assertLess(edited_text.find("==Demographics=="), edited_text.find("==References=="))

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
            '--codex-output-slot', '3',
        ]):
            args = parse_arguments()
        self.assertEqual(args.codex_output_slot, 3)

    def test_parse_arguments_accepts_enable_model_routing(self):
        with patch('sys.argv', [
            'poster.py',
            '--location', 'Sample County, Oklahoma',
            '--enable-model-routing',
        ]):
            args = parse_arguments()
        self.assertTrue(args.enable_model_routing)

    def test_parse_arguments_rejects_precompute_only_with_post_precomputed(self):
        with patch('sys.argv', [
            'poster.py',
            '--location', 'Sample County, Oklahoma',
            '--precompute-only',
            '--post-precomputed',
        ]):
            with self.assertRaises(SystemExit):
                parse_arguments()

    def test_parse_arguments_rejects_skip_logged_or_precomputed_with_post_precomputed(self):
        with patch('sys.argv', [
            'poster.py',
            '--location', 'Sample County, Oklahoma',
            '--post-precomputed',
            '--skip-logged-or-precomputed',
        ]):
            with self.assertRaises(SystemExit):
                parse_arguments()

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
            codex_output_slot=3,
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
                '3',
            )

    def test_main_sets_model_routing_env_when_requested(self):
        args = Mock(
            model=None,
            enable_model_routing=True,
            run_artifact_dir=None,
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
                os.environ.get(ENABLE_TASK_MODEL_ROUTING_ENV),
                '1',
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
            precompute_only=False,
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

    def test_main_skips_login_in_precompute_only_mode(self):
        args = Mock(
            model=None,
            run_artifact_dir=None,
            codex_home_dir=None,
            codex_output_slot=None,
            wait_for_claude_limit_reset=False,
            skip_logged_successes=False,
            precompute_only=True,
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
                with patch.object(poster, 'process_state_batch'):
                    main()

        client.login.assert_not_called()

    def test_main_unions_logged_and_precomputed_skip_sets(self):
        args = Mock(
            model=None,
            run_artifact_dir=None,
            codex_home_dir=None,
            codex_output_slot=None,
            wait_for_claude_limit_reset=False,
            skip_logged_successes=False,
            skip_logged_or_precomputed=True,
            precompute_only=False,
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
                with patch.object(poster, '_load_successful_articles', return_value={'Posted_A'}):
                    with patch.object(poster, '_load_precomputed_articles', return_value={'Cached_B'}):
                        with patch.object(poster, 'process_state_batch') as process_state_batch:
                            main()

        self.assertEqual(
            process_state_batch.call_args.kwargs['skip_successful_articles'],
            {'Posted_A', 'Cached_B'},
        )

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

    def test_process_state_batch_stops_after_current_article_when_interrupt_requested(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            county_file = root / "OK.json"
            county_file.write_text(
                json.dumps(
                    {
                        "Alpha County, Oklahoma": "county:40001",
                        "Beta County, Oklahoma": "county:40003",
                    }
                ),
                encoding="utf-8",
            )

            processed = []
            stop_state = {"value": False}

            def fake_should_stop():
                return stop_state["value"]

            def fake_process(*args, **kwargs):
                processed.append(args[0])
                stop_state["value"] = True

            with patch.object(poster, "COUNTY_FIPS_DIR", root):
                with patch.object(
                    poster,
                    "_should_stop_after_current_article",
                    side_effect=fake_should_stop,
                ):
                    with patch.object(
                        poster,
                        "process_single_article_with_retries",
                        side_effect=fake_process,
                    ):
                        poster.process_state_batch(
                            "OK",
                            client=None,
                            args=Mock(),
                            use_mini_prompt=False,
                        )

            self.assertEqual(processed, ["Alpha_County,_Oklahoma"])

    def test_process_municipality_batch_stops_after_current_article_when_interrupt_requested(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            places_dir = root / "OK" / "city"
            places_dir.mkdir(parents=True, exist_ok=True)
            (places_dir / "places.json").write_text(
                json.dumps(
                    {
                        "Alpha, Oklahoma": {
                            "state": "40",
                            "place": "00100",
                            "population": "100",
                        },
                        "Beta, Oklahoma": {
                            "state": "40",
                            "place": "00101",
                            "population": "101",
                        },
                    }
                ),
                encoding="utf-8",
            )

            processed = []
            stop_state = {"value": False}

            def fake_should_stop():
                return stop_state["value"]

            def fake_process(*args, **kwargs):
                processed.append(args[0])
                stop_state["value"] = True

            with patch.object(poster, "MUNICIPALITY_FIPS_DIR", root):
                with patch.object(
                    poster,
                    "_should_stop_after_current_article",
                    side_effect=fake_should_stop,
                ):
                    with patch.object(
                        poster,
                        "process_single_article_with_retries",
                        side_effect=fake_process,
                    ):
                        poster.process_municipality_batch(
                            "OK",
                            "city",
                            client=None,
                            args=Mock(min_muni_population=None, max_muni_population=None),
                            use_mini_prompt=False,
                        )

            self.assertEqual(processed, ["Alpha,_Oklahoma"])

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
