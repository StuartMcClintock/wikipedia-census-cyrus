#!/usr/bin/env python3
"""
Report logged-update coverage for municipalities that match state, type, and
population filters.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_LOG_PATH = BASE_DIR / "app_logging" / "logs" / "edit.log"
STATE_TO_FIPS_PATH = BASE_DIR / "census_api" / "fips_mappings" / "state_to_fips.json"
MUNICIPALITY_FIPS_DIR = BASE_DIR / "census_api" / "fips_mappings" / "municipality_to_fips"
NON_STATE_POSTALS = {"AS", "GU", "MP", "PR", "VI", "DC"}


def _split_csv_args(values: Optional[Sequence[str]]) -> List[str]:
    if not values:
        return []
    parts: List[str] = []
    for value in values:
        for piece in value.split(","):
            cleaned = piece.strip()
            if cleaned:
                parts.append(cleaned)
    return parts


def _parse_mapper_population(raw_value) -> Optional[int]:
    if raw_value is None:
        return None
    cleaned = str(raw_value).replace(",", "").strip()
    if not cleaned.isdigit():
        return None
    parsed = int(cleaned)
    return parsed if parsed >= 0 else None


def _normalize_article_title(title: str) -> str:
    return title.replace(" ", "_")


def _pct(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(100.0 * count / total, 1)


def _expand_state_postals(
    raw_states: Sequence[str], state_to_fips_path: Path = STATE_TO_FIPS_PATH
) -> List[str]:
    parts = [part.upper() for part in _split_csv_args(raw_states)]
    if not parts:
        return []
    if "ALL" in parts:
        data = json.loads(state_to_fips_path.read_text(encoding="utf-8"))
        return sorted(postal for postal in data if postal not in NON_STATE_POSTALS)
    return sorted(dict.fromkeys(parts))


def load_successful_articles(log_path: Path = DEFAULT_LOG_PATH) -> Set[str]:
    successes: Set[str] = set()
    if not log_path.exists():
        return successes
    with log_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            result = entry.get("result", {})
            edit = result.get("edit", {})
            if edit.get("result") != "Success":
                continue
            article = entry.get("article") or edit.get("title")
            if article:
                successes.add(_normalize_article_title(article))
    return successes


def _iter_filtered_municipalities(
    municipality_root: Path,
    states: Sequence[str],
    municipality_types: Sequence[str],
    min_population: Optional[int],
    max_population: Optional[int],
) -> Tuple[List[Dict[str, object]], int]:
    requested_types = {muni_type.lower() for muni_type in municipality_types}
    matches: List[Dict[str, object]] = []
    skipped_missing_population = 0

    for state_postal in states:
        state_dir = municipality_root / state_postal
        if not state_dir.exists():
            continue
        for type_dir in sorted(
            (entry for entry in state_dir.iterdir() if entry.is_dir()),
            key=lambda entry: entry.name.lower(),
        ):
            if type_dir.name.lower() not in requested_types:
                continue
            places_path = type_dir / "places.json"
            if not places_path.exists():
                continue
            place_map = json.loads(places_path.read_text(encoding="utf-8"))
            for article_title, codes in sorted(place_map.items(), key=lambda kv: kv[0].lower()):
                population = _parse_mapper_population(codes.get("population"))
                if min_population is not None or max_population is not None:
                    if population is None:
                        skipped_missing_population += 1
                        continue
                    if min_population is not None and population < min_population:
                        continue
                    if max_population is not None and population > max_population:
                        continue
                matches.append(
                    {
                        "article": article_title,
                        "normalized_article": _normalize_article_title(article_title),
                        "state_postal": state_postal,
                        "municipality_type": type_dir.name,
                        "population": population,
                    }
                )
    return matches, skipped_missing_population


def build_report(
    states: Sequence[str],
    municipality_types: Sequence[str],
    min_population: Optional[int] = None,
    max_population: Optional[int] = None,
    log_path: Path = DEFAULT_LOG_PATH,
    municipality_root: Path = MUNICIPALITY_FIPS_DIR,
) -> Dict[str, object]:
    logged_articles = load_successful_articles(log_path)
    matches, skipped_missing_population = _iter_filtered_municipalities(
        municipality_root=municipality_root,
        states=states,
        municipality_types=municipality_types,
        min_population=min_population,
        max_population=max_population,
    )

    logged_records: List[Dict[str, object]] = []
    unlogged_records: List[Dict[str, object]] = []
    grouped: Dict[Tuple[str, str], List[Dict[str, object]]] = defaultdict(list)

    for record in matches:
        grouped[(record["state_postal"], str(record["municipality_type"]))].append(record)
        if record["normalized_article"] in logged_articles:
            logged_records.append(record)
        else:
            unlogged_records.append(record)

    breakdown = []
    for state_postal, municipality_type in sorted(
        grouped.keys(), key=lambda key: (key[0], key[1].lower())
    ):
        records = grouped[(state_postal, municipality_type)]
        total = len(records)
        logged_count = sum(
            1 for record in records if record["normalized_article"] in logged_articles
        )
        unlogged_count = total - logged_count
        breakdown.append(
            {
                "state_postal": state_postal,
                "municipality_type": municipality_type,
                "total": total,
                "logged": logged_count,
                "unlogged": unlogged_count,
                "logged_pct": _pct(logged_count, total),
                "unlogged_pct": _pct(unlogged_count, total),
            }
        )

    total = len(matches)
    logged_count = len(logged_records)
    unlogged_count = len(unlogged_records)

    return {
        "states": list(states),
        "municipality_types": list(municipality_types),
        "min_population": min_population,
        "max_population": max_population,
        "total": total,
        "logged": logged_count,
        "unlogged": unlogged_count,
        "logged_pct": _pct(logged_count, total),
        "unlogged_pct": _pct(unlogged_count, total),
        "skipped_missing_population": skipped_missing_population,
        "logged_records": logged_records,
        "unlogged_records": unlogged_records,
        "breakdown": breakdown,
    }


def _format_population_range(
    min_population: Optional[int], max_population: Optional[int]
) -> str:
    if min_population is None and max_population is None:
        return "all populations"
    if min_population is None:
        return f"up to {max_population:,}"
    if max_population is None:
        return f"{min_population:,} and above"
    return f"{min_population:,} to {max_population:,}"


def _format_record(record: Dict[str, object]) -> str:
    population = record.get("population")
    population_text = f"{population:,}" if isinstance(population, int) else "unknown"
    return (
        f"{record['article']} "
        f"[{record['state_postal']} | {record['municipality_type']} | pop {population_text}]"
    )


def format_report(report: Dict[str, object], show_articles: str = "none") -> str:
    lines = [
        "Municipality log coverage",
        f"States: {', '.join(report['states'])}",
        f"Municipality types: {', '.join(str(item) for item in report['municipality_types'])}",
        "Population range: "
        + _format_population_range(report["min_population"], report["max_population"]),
        f"Matching municipalities: {report['total']}",
        f"Logged updates: {report['logged']} ({report['logged_pct']:.1f}%)",
        f"No logged updates: {report['unlogged']} ({report['unlogged_pct']:.1f}%)",
    ]

    if report["min_population"] is not None or report["max_population"] is not None:
        lines.append(
            "Skipped for missing population in mapper: "
            + str(report["skipped_missing_population"])
        )

    if report["breakdown"]:
        lines.append("")
        lines.append("By state/type:")
        for entry in report["breakdown"]:
            lines.append(
                f"- {entry['state_postal']} | {entry['municipality_type']}: "
                f"{entry['logged']}/{entry['total']} logged ({entry['logged_pct']:.1f}%), "
                f"{entry['unlogged']} unlogged ({entry['unlogged_pct']:.1f}%)"
            )

    if show_articles in {"logged", "all"}:
        lines.append("")
        lines.append("Logged municipalities:")
        if report["logged_records"]:
            lines.extend(f"- {_format_record(record)}" for record in report["logged_records"])
        else:
            lines.append("- None")

    if show_articles in {"unlogged", "all"}:
        lines.append("")
        lines.append("Unlogged municipalities:")
        if report["unlogged_records"]:
            lines.extend(f"- {_format_record(record)}" for record in report["unlogged_records"])
        else:
            lines.append("- None")

    return "\n".join(lines)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Count how many municipalities matching the selected filters do and "
            "do not have successful edit.log entries."
        )
    )
    parser.add_argument(
        "--state-postal",
        dest="state_postals",
        action="append",
        required=True,
        help="State postal code(s), comma-separated or repeated (e.g., CO,UT or --state-postal CO --state-postal UT). Use ALL for every state.",
    )
    parser.add_argument(
        "--municipality-type",
        dest="municipality_types",
        action="append",
        required=True,
        help="Municipality type(s), comma-separated or repeated (e.g., city,town or --municipality-type city --municipality-type town).",
    )
    parser.add_argument(
        "--min-population",
        type=int,
        help="Minimum mapper population to include.",
    )
    parser.add_argument(
        "--max-population",
        type=int,
        help="Maximum mapper population to include.",
    )
    parser.add_argument(
        "--show-articles",
        choices={"none", "logged", "unlogged", "all"},
        default="none",
        help="Optionally print the matching municipality titles.",
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help=f"Edit log to read (default: {DEFAULT_LOG_PATH}).",
    )
    parser.add_argument(
        "--municipality-root",
        type=Path,
        default=MUNICIPALITY_FIPS_DIR,
        help=f"Municipality mapping root (default: {MUNICIPALITY_FIPS_DIR}).",
    )
    args = parser.parse_args(argv)

    if args.min_population is not None and args.min_population < 0:
        parser.error("--min-population must be non-negative.")
    if args.max_population is not None and args.max_population < 0:
        parser.error("--max-population must be non-negative.")
    if (
        args.min_population is not None
        and args.max_population is not None
        and args.min_population > args.max_population
    ):
        parser.error("--min-population cannot be greater than --max-population.")

    args.state_postals = _expand_state_postals(args.state_postals)
    args.municipality_types = _split_csv_args(args.municipality_types)
    if not args.municipality_types:
        parser.error("Provide at least one --municipality-type.")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_report(
        states=args.state_postals,
        municipality_types=args.municipality_types,
        min_population=args.min_population,
        max_population=args.max_population,
        log_path=args.log_path,
        municipality_root=args.municipality_root,
    )
    print(format_report(report, show_articles=args.show_articles))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
