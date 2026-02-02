import unittest
from unittest.mock import patch

from ledes_poster import (
    _build_population_sentence,
    _fetch_place_population,
    _replace_lede_in_article,
    _extract_lede_wikitext,
    _append_diff_link,
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


if __name__ == "__main__":
    unittest.main()
