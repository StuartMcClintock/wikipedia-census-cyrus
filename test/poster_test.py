from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from poster import (
    apply_demographics_section_override,
    demographics_section_to_wikitext,
    find_demographics_section,
    WikipediaClient,
    WIKIPEDIA_ENDPOINT,
    ensure_us_location_title,
    parse_arguments,
)
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
            '--location', 'Sample, Oklahoma',
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
