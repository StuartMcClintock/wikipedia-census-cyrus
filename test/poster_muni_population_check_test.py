import json
import types
from unittest.mock import patch

from poster import process_municipality_batch, process_single_article


class DummyClient:
    def __init__(self, wikitext):
        self.wikitext = wikitext
        self.edits = 0

    def is_disambiguation_page(self, _title):
        return False

    def fetch_article_wikitext(self, _title):
        return self.wikitext

    def edit_article_wikitext(self, *args, **kwargs):
        self.edits += 1
        return {}


def test_process_single_article_skips_when_population_not_in_ballpark(monkeypatch):
    wikitext = """{{US Census population
| 2020 = 500
}}
==Demographics==
Text.
"""
    client = DummyClient(wikitext)
    args = types.SimpleNamespace(
        skip_should_update_check=True,
        skip_deterministic_fixes=False,
        show_codex_output=False,
        edit_summary=None,
        manual_review=False,
    )

    monkeypatch.setattr(
        "poster.determine_municipality_type",
        lambda _wikitext: {"type": "city", "reasons": ["test"]},
    )
    monkeypatch.setattr(
        "poster.generate_municipality_paragraphs",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not reach generation")),
    )

    process_single_article(
        "Sampleville,_Oklahoma",
        "40",
        "12345",
        args,
        client,
        use_mini_prompt=False,
        location_kind="municipality",
        expected_muni_type="city",
        expected_mapper_population=10000,
        use_population_ballpark_check=True,
    )

    assert client.edits == 0


def test_process_municipality_batch_passes_mapper_population(tmp_path):
    root = tmp_path / "municipality_to_fips"
    places_dir = root / "OK" / "city"
    places_dir.mkdir(parents=True, exist_ok=True)
    (places_dir / "places.json").write_text(
        json.dumps(
            {
                "Sampleville, Oklahoma": {
                    "state": "40",
                    "place": "12345",
                    "population": "3210",
                }
            }
        ),
        encoding="utf-8",
    )

    args = types.SimpleNamespace(min_muni_population=None, max_muni_population=None)
    with patch("poster.MUNICIPALITY_FIPS_DIR", root):
        with patch("poster.process_single_article_with_retries") as mock_process:
            process_municipality_batch(
                "OK",
                "city",
                client=None,
                args=args,
                use_mini_prompt=False,
            )

    assert mock_process.call_count == 1
    _, kwargs = mock_process.call_args
    assert kwargs["expected_mapper_population"] == 3210
    assert kwargs["use_population_ballpark_check"] is True


def test_process_municipality_batch_skips_below_population_threshold(tmp_path):
    root = tmp_path / "municipality_to_fips"
    places_dir = root / "OK" / "city"
    places_dir.mkdir(parents=True, exist_ok=True)
    (places_dir / "places.json").write_text(
        json.dumps(
            {
                "Smallville, Oklahoma": {
                    "state": "40",
                    "place": "10000",
                    "population": "900",
                },
                "Bigville, Oklahoma": {
                    "state": "40",
                    "place": "10001",
                    "population": "1500",
                },
            }
        ),
        encoding="utf-8",
    )

    args = types.SimpleNamespace(min_muni_population=1000, max_muni_population=None)
    with patch("poster.MUNICIPALITY_FIPS_DIR", root):
        with patch("poster.process_single_article_with_retries") as mock_process:
            process_municipality_batch(
                "OK",
                "city",
                client=None,
                args=args,
                use_mini_prompt=False,
            )

    assert mock_process.call_count == 1
    called_args, called_kwargs = mock_process.call_args
    assert called_args[0] == "Bigville,_Oklahoma"
    assert called_kwargs["expected_mapper_population"] == 1500


def test_process_municipality_batch_skips_above_population_threshold(tmp_path):
    root = tmp_path / "municipality_to_fips"
    places_dir = root / "OK" / "city"
    places_dir.mkdir(parents=True, exist_ok=True)
    (places_dir / "places.json").write_text(
        json.dumps(
            {
                "Smallville, Oklahoma": {
                    "state": "40",
                    "place": "10000",
                    "population": "900",
                },
                "Bigville, Oklahoma": {
                    "state": "40",
                    "place": "10001",
                    "population": "1500",
                },
            }
        ),
        encoding="utf-8",
    )

    args = types.SimpleNamespace(min_muni_population=None, max_muni_population=1000)
    with patch("poster.MUNICIPALITY_FIPS_DIR", root):
        with patch("poster.process_single_article_with_retries") as mock_process:
            process_municipality_batch(
                "OK",
                "city",
                client=None,
                args=args,
                use_mini_prompt=False,
            )

    assert mock_process.call_count == 1
    called_args, called_kwargs = mock_process.call_args
    assert called_args[0] == "Smallville,_Oklahoma"
    assert called_kwargs["expected_mapper_population"] == 900


def test_process_municipality_batch_skips_when_population_missing_and_threshold_set(tmp_path):
    root = tmp_path / "municipality_to_fips"
    places_dir = root / "OK" / "city"
    places_dir.mkdir(parents=True, exist_ok=True)
    (places_dir / "places.json").write_text(
        json.dumps(
            {
                "Unknownville, Oklahoma": {
                    "state": "40",
                    "place": "10000",
                },
            }
        ),
        encoding="utf-8",
    )

    args = types.SimpleNamespace(min_muni_population=1000, max_muni_population=None)
    with patch("poster.MUNICIPALITY_FIPS_DIR", root):
        with patch("poster.process_single_article_with_retries") as mock_process:
            process_municipality_batch(
                "OK",
                "city",
                client=None,
                args=args,
                use_mini_prompt=False,
            )

    mock_process.assert_not_called()
