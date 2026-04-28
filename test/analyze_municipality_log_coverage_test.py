import importlib.util
import json
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "analyze_municipality_log_coverage.py"
)
SPEC = importlib.util.spec_from_file_location(
    "analyze_municipality_log_coverage",
    MODULE_PATH,
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_build_report_filters_population_and_counts_successes(tmp_path):
    municipality_root = tmp_path / "municipality_to_fips"
    city_dir = municipality_root / "CO" / "city"
    city_dir.mkdir(parents=True, exist_ok=True)
    (city_dir / "places.json").write_text(
        json.dumps(
            {
                "Loggedville, Colorado": {
                    "state": "08",
                    "place": "01000",
                    "population": "1500",
                },
                "Unloggedville, Colorado": {
                    "state": "08",
                    "place": "01001",
                    "population": "2200",
                },
                "Missingpop, Colorado": {
                    "state": "08",
                    "place": "01002",
                },
                "Toosmall, Colorado": {
                    "state": "08",
                    "place": "01003",
                    "population": "999",
                },
            }
        ),
        encoding="utf-8",
    )

    log_path = tmp_path / "edit.log"
    log_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "article": "Loggedville,_Colorado",
                        "result": {"edit": {"result": "Success"}},
                    }
                ),
                json.dumps(
                    {
                        "article": "Unloggedville,_Colorado",
                        "result": {"edit": {"result": "Failure"}},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = MODULE.build_report(
        states=["CO"],
        municipality_types=["city"],
        min_population=1000,
        max_population=2500,
        log_path=log_path,
        municipality_root=municipality_root,
    )

    assert report["total"] == 2
    assert report["logged"] == 1
    assert report["unlogged"] == 1
    assert report["logged_pct"] == 50.0
    assert report["unlogged_pct"] == 50.0
    assert report["skipped_missing_population"] == 1
    assert report["breakdown"] == [
        {
            "state_postal": "CO",
            "municipality_type": "city",
            "total": 2,
            "logged": 1,
            "unlogged": 1,
            "logged_pct": 50.0,
            "unlogged_pct": 50.0,
        }
    ]


def test_parse_args_expands_all_and_repeated_types(tmp_path):
    state_to_fips_path = tmp_path / "state_to_fips.json"
    state_to_fips_path.write_text(
        json.dumps(
            {
                "CO": "state:08",
                "UT": "state:49",
                "PR": "state:72",
            }
        ),
        encoding="utf-8",
    )

    states = MODULE._expand_state_postals(["ALL"], state_to_fips_path=state_to_fips_path)
    municipality_types = MODULE._split_csv_args(["city,town", "village"])

    assert states == ["CO", "UT"]
    assert municipality_types == ["city", "town", "village"]
