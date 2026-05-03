#!/usr/bin/env python3
"""
Build a fine-tuning dataset by pairing each precomputed (LLM-edited) demographics
section with the *current* (unedited) demographics section pulled from Wikipedia.

A pair is only kept if the article on Wikipedia has not been edited since the
precompute timestamp recorded in the manifest. That guarantees the section we
pull now is byte-identical to what the LLM was originally given as input.

Output:
  fine_tuning/pairs.jsonl   - one JSON object per kept pair
  fine_tuning/skipped.jsonl - one JSON object per skipped entry, with reason
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from parser.parser import ParsedWikitext  # noqa: E402

WIKIPEDIA_ENDPOINT = "https://en.wikipedia.org/w/api.php"
DEFAULT_USER_AGENT = (
    "wikipedia-census-cyrus fine-tuning corpus builder "
    "(https://github.com/StuartMcClintock/wikipedia-census-cyrus)"
)
SECTION_SENTINELS = {"__lead__", "__content__"}

PRECOMPUTED_ROOT = Path(__file__).resolve().parent / "precomputed"
PAIRS_PATH = Path(__file__).resolve().parent / "pairs.jsonl"
SKIPPED_PATH = Path(__file__).resolve().parent / "skipped.jsonl"


def parse_iso8601(value: str) -> datetime:
    """Parse an ISO-8601 timestamp (with optional trailing 'Z') into an aware UTC datetime."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fetch_latest_revision(
    session: requests.Session, title: str
) -> Tuple[str, str, str]:
    """
    Return (resolved_title, wikitext, last_edit_timestamp_iso) for the latest revision.
    """
    params = {
        "action": "query",
        "prop": "revisions",
        "titles": title,
        "rvprop": "content|timestamp",
        "rvslots": "main",
        "redirects": 1,
        "formatversion": "2",
        "format": "json",
    }
    response = session.get(WIKIPEDIA_ENDPOINT, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    pages = data.get("query", {}).get("pages", [])
    if not pages:
        raise ValueError(f"Wikipedia returned no page data for '{title}'.")
    page = pages[0]
    if "missing" in page:
        raise ValueError(f"Wikipedia article '{title}' does not exist.")
    if "invalidreason" in page:
        raise ValueError(f"Invalid title '{title}': {page['invalidreason']}.")
    if "revisions" not in page or not page["revisions"]:
        raise ValueError(f"Wikipedia response for '{title}' has no revisions.")

    revision = page["revisions"][0]
    return (
        page["title"],
        revision["slots"]["main"]["content"],
        revision["timestamp"],
    )


def extract_demographics_section(article_wikitext: str) -> Optional[str]:
    """
    Locate the top-level ==Demographics== section in article_wikitext and return
    it (heading + body + nested subsections) as wikitext. Returns None if not found.
    """
    parsed = ParsedWikitext(wikitext=article_wikitext)
    for entry in parsed.sections:
        heading = entry[0]
        if heading in SECTION_SENTINELS:
            continue
        if heading == "Demographics":
            return ParsedWikitext(sections=[entry]).to_wikitext()
    return None


def iter_manifests(precomputed_root: Path) -> List[Path]:
    return sorted(precomputed_root.rglob("manifest.json"))


def append_jsonl(path: Path, record: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--precomputed-root",
        type=Path,
        default=PRECOMPUTED_ROOT,
        help="Directory containing precomputed manifests (default: %(default)s).",
    )
    parser.add_argument(
        "--pairs-out",
        type=Path,
        default=PAIRS_PATH,
        help="Path to write kept (input, output) pairs as JSONL.",
    )
    parser.add_argument(
        "--skipped-out",
        type=Path,
        default=SKIPPED_PATH,
        help="Path to write skipped entries (with reason) as JSONL.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="If set, process at most N manifests (useful for smoke tests).",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.25,
        help="Seconds to sleep between Wikipedia API calls (default: %(default)s).",
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="User-Agent header sent to the Wikipedia API.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Truncate pairs/skipped output files before writing.",
    )
    args = parser.parse_args()

    if args.overwrite:
        for path in (args.pairs_out, args.skipped_out):
            if path.exists():
                path.unlink()

    manifests = iter_manifests(args.precomputed_root)
    if args.limit is not None:
        manifests = manifests[: args.limit]
    if not manifests:
        print(f"No manifests found under {args.precomputed_root}.", file=sys.stderr)
        return 1

    session = requests.Session()
    session.headers.update({"User-Agent": args.user_agent})

    kept = 0
    skipped = 0
    failed = 0

    for index, manifest_path in enumerate(manifests, start=1):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[{index}/{len(manifests)}] unreadable manifest {manifest_path}: {exc}")
            failed += 1
            continue

        article_title = manifest["article"]
        precompute_ts = parse_iso8601(manifest["timestamp"])
        edited_section_path = manifest_path.parent / "demographics_section.wikitext"

        if not manifest.get("had_demographics_section", True):
            append_jsonl(
                args.skipped_out,
                {
                    "article": article_title,
                    "manifest_path": str(manifest_path),
                    "reason": "no_pre_existing_demographics_section",
                },
            )
            skipped += 1
            print(f"[{index}/{len(manifests)}] skip {article_title}: no pre-existing section")
            continue

        if not edited_section_path.exists():
            append_jsonl(
                args.skipped_out,
                {
                    "article": article_title,
                    "manifest_path": str(manifest_path),
                    "reason": "missing_precomputed_section_file",
                },
            )
            skipped += 1
            print(f"[{index}/{len(manifests)}] skip {article_title}: missing edited section file")
            continue

        try:
            resolved_title, wikitext, last_edit_str = fetch_latest_revision(
                session, article_title
            )
        except Exception as exc:
            append_jsonl(
                args.skipped_out,
                {
                    "article": article_title,
                    "manifest_path": str(manifest_path),
                    "reason": "fetch_failed",
                    "detail": str(exc),
                },
            )
            failed += 1
            print(f"[{index}/{len(manifests)}] fetch failed {article_title}: {exc}")
            time.sleep(args.sleep)
            continue

        last_edit_ts = parse_iso8601(last_edit_str)

        if last_edit_ts > precompute_ts:
            append_jsonl(
                args.skipped_out,
                {
                    "article": article_title,
                    "resolved_title": resolved_title,
                    "manifest_path": str(manifest_path),
                    "reason": "edited_after_precompute",
                    "manifest_timestamp": manifest["timestamp"],
                    "last_edit_timestamp": last_edit_str,
                },
            )
            skipped += 1
            print(
                f"[{index}/{len(manifests)}] skip {article_title}: "
                f"edited {last_edit_str} > precompute {manifest['timestamp']}"
            )
            time.sleep(args.sleep)
            continue

        current_section = extract_demographics_section(wikitext)
        if current_section is None:
            append_jsonl(
                args.skipped_out,
                {
                    "article": article_title,
                    "resolved_title": resolved_title,
                    "manifest_path": str(manifest_path),
                    "reason": "demographics_section_not_found_in_current_wikitext",
                },
            )
            skipped += 1
            print(f"[{index}/{len(manifests)}] skip {article_title}: no Demographics section in current article")
            time.sleep(args.sleep)
            continue

        current_section_path = manifest_path.parent / "current_demographics_section.wikitext"
        current_section_path.write_text(current_section, encoding="utf-8")

        edited_section = edited_section_path.read_text(encoding="utf-8")

        append_jsonl(
            args.pairs_out,
            {
                "article": article_title,
                "resolved_title": resolved_title,
                "state_fips": manifest.get("state_fips"),
                "target_fips": manifest.get("target_fips"),
                "location_kind": manifest.get("location_kind"),
                "model": manifest.get("model"),
                "manifest_timestamp": manifest["timestamp"],
                "last_edit_timestamp": last_edit_str,
                "input": current_section,
                "output": edited_section,
            },
        )
        kept += 1
        print(f"[{index}/{len(manifests)}] keep {article_title}")
        time.sleep(args.sleep)

    print(
        f"\nDone. kept={kept} skipped={skipped} failed={failed} "
        f"(pairs: {args.pairs_out}, skipped log: {args.skipped_out})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
