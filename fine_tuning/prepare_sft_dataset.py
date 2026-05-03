#!/usr/bin/env python3
"""
Convert fine_tuning/pairs.jsonl into an OpenAI supervised fine-tuning dataset
for chat models (gpt-4.1-mini-2025-04-14).

For each (current_demographics_section, edited_demographics_section) pair, this
script:
  1. Re-generates the proposed `new_text` (the 2020-census paragraph block) by
     calling the project's existing `generate_municipality_paragraphs(...)`.
     The result is cached on disk next to the manifest so reruns are cheap and
     reproducible.
  2. Builds an OpenAI chat fine-tuning record:
        {"messages": [
            {"role": "system",    "content": SYSTEM_PROMPT},
            {"role": "user",      "content": USER_PROMPT.format(...)},
            {"role": "assistant", "content": <edited section>},
        ]}
     The system + user prompt mirror llm_backends/openai_gpt_5_mini/openai_gpt_5_mini.py
     (the only chat-API backend in the project) so a fine-tuned 4.1-mini model
     can drop into that same call shape.
  3. Validates each record (non-empty, role order, output looks like wikitext).
     Bad records are quarantined, not silently dropped.
  4. Deduplicates exact (input + new_text + output) hashes.
  5. Splits 90/10 train/eval with a fixed seed. Each article appears in only
     one split (no leakage; articles are unique in pairs.jsonl anyway).
  6. Writes train.jsonl, eval.jsonl, quarantined.jsonl, and dataset_report.md.

Original pairs.jsonl is NEVER modified. New cache files live under
fine_tuning/precomputed/<...>/new_text.wikitext.
"""

import argparse
import hashlib
import json
import random
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

# Project imports — these touch the Census API.
from municipality.generate_municipality_paragraphs import generate_municipality_paragraphs  # noqa: E402

PAIRS_PATH = Path(__file__).resolve().parent / "pairs.jsonl"
PRECOMPUTED_ROOT = Path(__file__).resolve().parent / "precomputed"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "artifacts" / "fine_tuning"
NEW_TEXT_CACHE_FILENAME = "new_text.wikitext"

DEFAULT_SEED = 1234
DEFAULT_EVAL_FRACTION = 0.10
MIN_TRAIN_EXAMPLES = 10
VALID_ROLES = {"system", "developer", "user", "assistant"}

# System prompt copied verbatim from llm_backends/openai_gpt_5_mini/openai_gpt_5_mini.py
# so a fine-tuned model can drop into that backend without prompt drift.
SYSTEM_PROMPT = (
    "You are an expert Wikipedia editor focused on demographics sections. "
    "Follow the instructions precisely and return only valid wikitext."
)

# User prompt body copied verbatim from openai_gpt_5_mini.update_demographics_section
# (minus the trailing data fields, which are interpolated below).
USER_PROMPT_TEMPLATE = """\
In the message you will be provided with "current_demographics_section", which contains the current text for the demographics section of a Wikipedia article for a county or municipality in the United States.

You will also be provided with "new_text", which contains proposed new text you must add to this demographics section. It is composed entirely of data from the 2020 US Census.

Modify the existing demographics section to contain the new 2020 census data, adding a new "===2020 census===" section or integrating with a pre-existing one as needed.

Keep references intact, and do not change factual content beyond inserting the 2020 census data. Be careful with headings, tables and refs to ensure that you don't break the wikitext.

Remove information made redundant by the new data. If needed, rearrange sentences containing existing demographic information so that it is grouped with related sentences in a logically flowing manner. If appropriate, put another H3 header below the new ===2020 census=== section in order to clearly mark where the 2020 census stops. The new header should meaningfully describe the content that comes below it in a way that is consistent with established section-naming precedent in Wikipedia.

If there is a wikitable on racial/ethnic composition across multiple decades, put it in it's own "===Racial and ethnic composition===" section. Keep in mind that sometimes the racial and ethnic composition section is called something like "Demographic Profile".

Do not remove old data (eg 2000 or 2010 census data), just move it into its own properly labeled subsection (eg "===2010 census===" or "===2000 census===")

Do not delete large chunks of existing content even if it seems irrelevant to demographics (eg a "===Crime===" section). You may move, modify, and add headings - but never just delete a bunch of content.

Output only the updated demographics and related census sections (no commentary).

current_demographics_section:
{current_demographics_section}

new_text:
{new_text}
"""


# ---------------------------------------------------------------------------
# new_text cache: regenerate-on-miss, deterministic per (state, place) FIPS.
# ---------------------------------------------------------------------------


def find_manifest_dir(state_fips: str, target_fips: str) -> Optional[Path]:
    """Locate the precomputed manifest directory for a (state, place) pair."""
    state_dir = PRECOMPUTED_ROOT / "municipality" / str(state_fips).zfill(2) / str(target_fips)
    if not state_dir.exists():
        return None
    # Each (state, place) maps to exactly one article directory.
    children = [p for p in state_dir.iterdir() if p.is_dir()]
    return children[0] if children else None


def get_or_build_new_text(
    state_fips: str,
    target_fips: str,
    sleep_between_fetches: float,
    refresh: bool = False,
) -> str:
    """
    Return new_text for the article. Use the on-disk cache when available,
    otherwise call the Census API and write the cache.
    """
    manifest_dir = find_manifest_dir(state_fips, target_fips)
    cache_path = manifest_dir / NEW_TEXT_CACHE_FILENAME if manifest_dir else None

    if cache_path and cache_path.exists() and not refresh:
        return cache_path.read_text(encoding="utf-8")

    # Cache miss: hit the Census API. The project's generator function fetches
    # multiple census tables; pad with a small sleep to be polite.
    new_text = generate_municipality_paragraphs(
        state_fips=str(state_fips).zfill(2),
        place_fips=str(target_fips),
        full_first_paragraph_refs=True,
    )
    if not isinstance(new_text, str) or not new_text.strip():
        raise RuntimeError(
            f"generate_municipality_paragraphs returned empty content for "
            f"state={state_fips} place={target_fips}"
        )

    if cache_path:
        cache_path.write_text(new_text, encoding="utf-8")
    if sleep_between_fetches > 0:
        time.sleep(sleep_between_fetches)
    return new_text


# ---------------------------------------------------------------------------
# Per-record validation. Quarantine on failure rather than silently drop.
# ---------------------------------------------------------------------------


_BRACE_TEMPLATE_OPEN_RE = re.compile(r"\{\{")
_BRACE_TEMPLATE_CLOSE_RE = re.compile(r"\}\}")


def validate_record(record: Dict) -> Optional[str]:
    """Return None if record is OK, else a short string describing the problem."""
    messages = record.get("messages")
    if not isinstance(messages, list) or len(messages) < 2:
        return "messages list missing or too short"

    roles = [m.get("role") for m in messages]
    if any(role not in VALID_ROLES for role in roles):
        return f"invalid role(s): {roles}"

    if messages[-1].get("role") != "assistant":
        return "last message is not assistant"

    for m in messages:
        content = m.get("content")
        if not isinstance(content, str) or not content.strip():
            return f"empty content in role={m.get('role')}"

    user_content = next(
        (m["content"] for m in messages if m["role"] == "user"), ""
    )
    assistant_content = messages[-1]["content"]

    # Sanity bounds — these catch obvious corruption (truncated current section,
    # placeholder text, model error message that slipped through).
    if "current_demographics_section:" not in user_content:
        return "user content missing current_demographics_section: marker"
    if "new_text:" not in user_content:
        return "user content missing new_text: marker"
    if len(assistant_content) < 200:
        return f"assistant content suspiciously short ({len(assistant_content)} chars)"

    # Mismatched template braces in the assistant output usually means the LLM
    # truncated mid-citation — not training-quality data.
    open_n = len(_BRACE_TEMPLATE_OPEN_RE.findall(assistant_content))
    close_n = len(_BRACE_TEMPLATE_CLOSE_RE.findall(assistant_content))
    if abs(open_n - close_n) > 1:
        return f"unbalanced {{{{ }}}} templates in assistant output ({open_n} vs {close_n})"

    return None


# ---------------------------------------------------------------------------
# Dataset assembly
# ---------------------------------------------------------------------------


def build_record(pair: Dict, new_text: str) -> Dict:
    """Build the OpenAI chat fine-tuning record for one pair."""
    user_content = USER_PROMPT_TEMPLATE.format(
        current_demographics_section=pair["input"].rstrip(),
        new_text=new_text.rstrip(),
    )
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": pair["output"].rstrip()},
        ]
    }


def hash_record(record: Dict) -> str:
    """Stable content hash for dedup."""
    payload = json.dumps(record["messages"], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_jsonl(path: Path, records: List[Dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Cheap estimate: ~4 chars per token for English+wikitext mix."""
    return max(1, len(text) // 4)


def render_report(
    output_dir: Path,
    n_source: int,
    n_train: int,
    n_eval: int,
    quarantined: List[Tuple[str, str]],
    skipped_no_new_text: List[Tuple[str, str]],
    duplicates_dropped: List[str],
    state_distribution: Dict[str, int],
    train_records: List[Dict],
) -> str:
    avg_user_tokens = (
        sum(estimate_tokens(r["messages"][1]["content"]) for r in train_records)
        // max(1, len(train_records))
    )
    avg_asst_tokens = (
        sum(estimate_tokens(r["messages"][-1]["content"]) for r in train_records)
        // max(1, len(train_records))
    )
    total_train_tokens = sum(
        estimate_tokens(r["messages"][1]["content"])
        + estimate_tokens(r["messages"][-1]["content"])
        for r in train_records
    )

    sample_lines: List[str] = []
    for sample in train_records[:2]:
        user = sample["messages"][1]["content"]
        asst = sample["messages"][-1]["content"]
        sample_lines.append("```")
        sample_lines.append("USER (truncated):")
        sample_lines.append(user[:600] + ("..." if len(user) > 600 else ""))
        sample_lines.append("")
        sample_lines.append("ASSISTANT (truncated):")
        sample_lines.append(asst[:600] + ("..." if len(asst) > 600 else ""))
        sample_lines.append("```")
        sample_lines.append("")

    quarantine_lines = (
        "\n".join(f"- `{a}` — {reason}" for a, reason in quarantined[:10])
        if quarantined
        else "- (none)"
    )
    no_new_text_lines = (
        "\n".join(f"- `{a}` — {reason}" for a, reason in skipped_no_new_text[:10])
        if skipped_no_new_text
        else "- (none)"
    )
    dup_lines = (
        "\n".join(f"- `{a}`" for a in duplicates_dropped[:10])
        if duplicates_dropped
        else "- (none)"
    )
    state_lines = "\n".join(
        f"- state FIPS `{k}`: {v}" for k, v in sorted(state_distribution.items())
    )

    try:
        display_dir = output_dir.relative_to(ROOT_DIR)
    except ValueError:
        display_dir = output_dir

    return f"""# Fine-tuning dataset report

**Target model:** `gpt-4.1-mini-2025-04-14`
**Output directory:** `{display_dir}`

## Counts

| | count |
|---|---|
| Source pairs (`pairs.jsonl`) | {n_source} |
| Quarantined (validation failed) | {len(quarantined)} |
| Skipped (could not regenerate `new_text`) | {len(skipped_no_new_text)} |
| Duplicates dropped | {len(duplicates_dropped)} |
| **Train examples** | **{n_train}** |
| **Eval examples** | **{n_eval}** |

## Distribution by state FIPS
{state_lines if state_lines else "- (none)"}

## Token estimates (per example, ~4 chars/token)
- Average user-prompt tokens: ~{avg_user_tokens}
- Average assistant-output tokens: ~{avg_asst_tokens}
- Estimated total training tokens (train set, 1 epoch): ~{total_train_tokens:,}

## Quarantined examples (first 10)
{quarantine_lines}

## Skipped — Census API regeneration failed (first 10)
{no_new_text_lines}

## Duplicates dropped (first 10)
{dup_lines}

## Sample examples (truncated)
{chr(10).join(sample_lines)}

## Data quality concerns
- All source examples come from a single state (Iowa, FIPS 19) and a single
  generator model (`gpt-5.3-codex`). The fine-tuned model will be fit to that
  output style — if it differs noticeably from what you want, expand the corpus
  before scaling up.
- The `new_text` field is regenerated *now* from the Census API, while the
  outputs were produced earlier with whatever `new_text` the generator emitted
  at precompute time. Small drifts are possible if `generate_municipality_paragraphs`
  has changed since.
- All examples are full-page wikitext rewrites, which makes evaluation expensive
  and noisy. Plan to spot-check a handful of generated outputs by hand.

## Recommended first run
- Start with this corpus as-is for a single fine-tune run.
- Default OpenAI hyperparameters (auto) are fine; do not hand-tune until you
  have a baseline metric to compare against.
- Estimated training tokens: ~{total_train_tokens:,} (1 epoch) / ~{total_train_tokens * 3:,} (3 epochs).
  Check current `gpt-4.1-mini` fine-tuning pricing before starting the job.

## Next data improvements
1. Add a second state (e.g. Texas, Ohio) to test geographic generalization.
2. Add county-level examples (currently municipality only).
3. Manually spot-check 10 outputs and quarantine any that drop refs, mangle
   tables, or hallucinate numbers.
4. Capture the *exact* `new_text` used at generation time during precompute,
   so you don't have to regenerate.
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pairs",
        type=Path,
        default=PAIRS_PATH,
        help="Path to pairs.jsonl produced by build_training_data.py",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to write train.jsonl, eval.jsonl, etc.",
    )
    parser.add_argument(
        "--eval-fraction",
        type=float,
        default=DEFAULT_EVAL_FRACTION,
        help="Fraction of records held out for eval (default: %(default)s).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="Random seed for deterministic splits.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N pairs (smoke testing).",
    )
    parser.add_argument(
        "--census-sleep",
        type=float,
        default=0.2,
        help="Seconds to sleep between Census API requests (default: %(default)s).",
    )
    parser.add_argument(
        "--refresh-new-text",
        action="store_true",
        help="Force regenerate cached new_text files even if present.",
    )
    args = parser.parse_args()

    if not args.pairs.exists():
        print(f"Pairs file not found: {args.pairs}", file=sys.stderr)
        return 1

    pairs: List[Dict] = []
    with args.pairs.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            pairs.append(json.loads(line))
    if args.limit is not None:
        pairs = pairs[: args.limit]
    print(f"Loaded {len(pairs)} source pairs from {args.pairs}")

    quarantined: List[Tuple[str, str]] = []
    skipped_no_new_text: List[Tuple[str, str]] = []
    duplicates_dropped: List[str] = []
    quarantine_records: List[Dict] = []
    final_records: List[Tuple[str, Dict]] = []  # (article, record)
    seen_hashes: Dict[str, str] = {}  # hash -> article

    for index, pair in enumerate(pairs, start=1):
        article = pair.get("article", "<unknown>")
        state_fips = pair.get("state_fips")
        target_fips = pair.get("target_fips")
        if not state_fips or not target_fips:
            quarantined.append((article, "missing state_fips/target_fips in pair"))
            quarantine_records.append({"article": article, "reason": "missing fips", "pair": pair})
            print(f"[{index}/{len(pairs)}] quarantine {article}: missing fips")
            continue

        try:
            new_text = get_or_build_new_text(
                state_fips, target_fips, args.census_sleep, refresh=args.refresh_new_text
            )
        except Exception as exc:
            skipped_no_new_text.append((article, str(exc)[:200]))
            print(f"[{index}/{len(pairs)}] skip {article}: new_text failed ({exc})")
            continue

        record = build_record(pair, new_text)
        problem = validate_record(record)
        if problem is not None:
            quarantined.append((article, problem))
            quarantine_records.append(
                {"article": article, "reason": problem, "record": record}
            )
            print(f"[{index}/{len(pairs)}] quarantine {article}: {problem}")
            continue

        h = hash_record(record)
        if h in seen_hashes:
            duplicates_dropped.append(article)
            print(f"[{index}/{len(pairs)}] dup {article} (matches {seen_hashes[h]})")
            continue
        seen_hashes[h] = article

        final_records.append((article, record))
        print(f"[{index}/{len(pairs)}] kept {article}")

    if len(final_records) < MIN_TRAIN_EXAMPLES:
        print(
            f"\nERROR: only {len(final_records)} valid examples — need at least "
            f"{MIN_TRAIN_EXAMPLES} for fine-tuning. Aborting before split.",
            file=sys.stderr,
        )
        return 2

    # Deterministic split. Sort first so order doesn't depend on filesystem
    # iteration order, then shuffle with a fixed seed.
    final_records.sort(key=lambda x: x[0])
    rng = random.Random(args.seed)
    rng.shuffle(final_records)

    n_eval = max(1, int(round(len(final_records) * args.eval_fraction)))
    eval_records = final_records[:n_eval]
    train_records = final_records[n_eval:]

    state_distribution: Dict[str, int] = {}
    for _, record in train_records + eval_records:
        # Pull state FIPS back from the user content's article context — but
        # easier to just trust pair-side info. Skip; we already report counts.
        pass
    # Simpler: redo from source pairs (they're 1:1 with final_records by article).
    article_to_state = {p["article"]: p.get("state_fips") for p in pairs}
    for article, _ in train_records + eval_records:
        s = article_to_state.get(article, "?")
        state_distribution[s] = state_distribution.get(s, 0) + 1

    train_path = args.output_dir / "train.jsonl"
    eval_path = args.output_dir / "eval.jsonl"
    quarantined_path = args.output_dir / "quarantined.jsonl"
    report_path = args.output_dir / "dataset_report.md"

    write_jsonl(train_path, [r for _, r in train_records])
    write_jsonl(eval_path, [r for _, r in eval_records])
    write_jsonl(quarantined_path, quarantine_records)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(
            output_dir=args.output_dir,
            n_source=len(pairs),
            n_train=len(train_records),
            n_eval=len(eval_records),
            quarantined=quarantined,
            skipped_no_new_text=skipped_no_new_text,
            duplicates_dropped=duplicates_dropped,
            state_distribution=state_distribution,
            train_records=[r for _, r in train_records],
        ),
        encoding="utf-8",
    )

    print(
        f"\nWrote:\n  {train_path}  ({len(train_records)} examples)\n"
        f"  {eval_path}  ({len(eval_records)} examples)\n"
        f"  {quarantined_path}  ({len(quarantine_records)} quarantined)\n"
        f"  {report_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
