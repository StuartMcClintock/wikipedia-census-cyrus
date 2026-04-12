from municipality.muni_type_classifier import (
    check_population_ballpark_against_history,
    extract_most_recent_population_from_history,
)


def test_extract_most_recent_population_from_history():
    wikitext = """{{US Census population
| 2010 = 1,234
| 2020 = 2,345
}}
"""
    assert extract_most_recent_population_from_history(wikitext) == (2020, 2345)


def test_population_ballpark_check_skips_when_history_missing():
    wikitext = "==History==\nNo population table here.\n"
    result = check_population_ballpark_against_history(wikitext, mapper_population=1200)
    assert result["check_performed"] is False
    assert result["in_ballpark"] is True


def test_population_ballpark_check_fails_on_large_mismatch():
    wikitext = """{{US Census population
| 2020 = 500
}}
"""
    result = check_population_ballpark_against_history(wikitext, mapper_population=10000)
    assert result["check_performed"] is True
    assert result["in_ballpark"] is False
